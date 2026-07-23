import json
import os
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from graph.recipe_parser import make_node_id
from utils.config_handler import chroma_conf, rag_conf
from utils.file_handler import (
    get_file_md5_hex,
    listdir_with_allowed_type,
    markdown_loader,
    pdf_loader,
    txt_loader,
)
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


def _build_embedding_model() -> HuggingFaceEmbeddings:
    model_path = get_abs_path(
        rag_conf.get(
            "embedding_model_path",
            "model/embeddingmodels/bge-small-zh-v1.5",
        )
    )
    if not os.path.isdir(model_path):
        raise FileNotFoundError(f"本地嵌入模型目录不存在：{model_path}")
    return HuggingFaceEmbeddings(
        model_name=model_path,
        model_kwargs={
            "device": rag_conf.get("embedding_device", "cpu"),
            "local_files_only": bool(rag_conf.get("embedding_offline", True)),
        },
        encode_kwargs={"normalize_embeddings": True},
    )


embed_model = _build_embedding_model()


# 父子块检索类
class ParentChildRetriever:
    """Retrieve small vector-matched child chunks, then return parent chunks."""

    def __init__(
        self,
        vector_store: Chroma,
        parent_store_path: str,
        child_k: int,
        parent_k: int,
    ):
        self.vector_store = vector_store
        self.parent_store_path = parent_store_path
        self.child_k = child_k
        self.parent_k = parent_k

    def _load_parent_store(self) -> dict[str, dict[str, Any]]:
        if not os.path.exists(self.parent_store_path):
            return {}

        with open(self.parent_store_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def invoke(
        self,
        query: str,
        candidate_recipe_ids: list[str] | None = None,
        parent_k: int | None = None,
    ) -> list[Document]:
        metadata_filter = None
        if candidate_recipe_ids:
            metadata_filter = {
                "recipe_id": {
                    "$in": candidate_recipe_ids,
                }
            }

        child_docs = self.vector_store.similarity_search(
            query,
            k=self.child_k,
            filter=metadata_filter,
        )
        parent_store = self._load_parent_store()
        max_parent_docs = parent_k or self.parent_k

        parent_docs: list[Document] = []
        seen_parent_ids: set[str] = set()

        for child_doc in child_docs:
            parent_id = child_doc.metadata.get("parent_id")

            if not parent_id:
                parent_docs.append(child_doc)
                continue

            if parent_id in seen_parent_ids:
                continue

            parent_payload = parent_store.get(parent_id)

            if not parent_payload:
                parent_docs.append(child_doc)
                continue

            parent_docs.append(
                Document(
                    page_content=parent_payload["page_content"],
                    metadata=parent_payload.get("metadata", {}),
                )
            )
            seen_parent_ids.add(parent_id)

            if len(parent_docs) >= max_parent_docs:
                break

        return parent_docs

    def invoke_in_recipes(
        self,
        query: str,
        recipe_ids: list[str],
    ) -> list[Document]:
        if not recipe_ids:
            return []

        return self.invoke(
            query=query,
            candidate_recipe_ids=recipe_ids,
        )


class VectorStoreService:
    def __init__(self):
        self.vector_store = Chroma(
            collection_name=chroma_conf["collection_name"],
            embedding_function=embed_model,
            persist_directory=get_abs_path(chroma_conf["persist_directory"]),
        )

        self.child_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],
            chunk_overlap=chroma_conf["chunk_overlap"],
            separators=chroma_conf["separators"],
            length_function=len,
        )

        self.parent_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf.get("parent_chunk_size", 1800),
            chunk_overlap=chroma_conf.get("parent_chunk_overlap", 200),
            separators=chroma_conf["separators"],
            length_function=len,
        )

        self.parent_store_path = get_abs_path(
            chroma_conf.get("parent_doc_store", "storage/parent_documents.json")
        )

    def get_retriever(self):
        return ParentChildRetriever(
            vector_store=self.vector_store,
            parent_store_path=self.parent_store_path,
            child_k=chroma_conf.get("child_k", chroma_conf["k"] * 3),
            parent_k=chroma_conf["k"],
        )

    def _load_parent_store(self) -> dict[str, dict[str, Any]]:
        if not os.path.exists(self.parent_store_path):
            return {}

        with open(self.parent_store_path, "r", encoding="utf-8") as file:
            return json.load(file)

    def _save_parent_store(self, parent_store: dict[str, dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(self.parent_store_path), exist_ok=True)

        with open(self.parent_store_path, "w", encoding="utf-8") as file:
            json.dump(parent_store, file, ensure_ascii=False, indent=2)

    def _check_md5_hex(self, md5_for_check: str) -> bool:
        md5_store_path = get_abs_path(chroma_conf["md5_hex_store"])
        os.makedirs(os.path.dirname(md5_store_path), exist_ok=True)

        if not os.path.exists(md5_store_path):
            open(md5_store_path, "w", encoding="utf-8").close()
            return False

        with open(md5_store_path, "r", encoding="utf-8") as file:
            return any(line.strip() == md5_for_check for line in file)

    def _save_md5_hex(self, md5_for_check: str) -> None:
        md5_store_path = get_abs_path(chroma_conf["md5_hex_store"])
        os.makedirs(os.path.dirname(md5_store_path), exist_ok=True)

        with open(md5_store_path, "a", encoding="utf-8") as file:
            file.write(md5_for_check + "\n")

    def _get_file_documents(self, read_path: str) -> list[Document]:
        suffix = os.path.splitext(read_path)[1].lower()

        if suffix == ".txt":
            return txt_loader(read_path)

        if suffix == ".pdf":
            return pdf_loader(read_path)

        if suffix in {".md", ".markdown"}:
            return markdown_loader(read_path)

        return []

    #构建父块和子块
    def _build_parent_child_documents(
        self,
        documents: list[Document],
        file_md5: str,
        recipe_id: str,
        parent_store: dict[str, dict[str, Any]],
    ) -> list[Document]:
        parent_docs = self.parent_splitter.split_documents(documents)
        child_docs: list[Document] = []

        for parent_index, parent_doc in enumerate(parent_docs):
            parent_id = f"{recipe_id}:parent:{parent_index}"
            parent_metadata = {
                **parent_doc.metadata,
                "recipe_id": recipe_id,
                "node_id": recipe_id,
                "file_md5": file_md5,
                "parent_id": parent_id,
                "chunk_role": "parent",
                "parent_index": parent_index,
            }

            parent_store[parent_id] = {
                "page_content": parent_doc.page_content,
                "metadata": parent_metadata,
            }

            children = self.child_splitter.split_documents(
                [
                    Document(
                        page_content=parent_doc.page_content,
                        metadata=parent_metadata,
                    )
                ]
            )

            for child_index, child_doc in enumerate(children):
                child_doc.metadata.update(
                    {
                        "recipe_id": recipe_id,
                        "node_id": recipe_id,
                        "file_md5": file_md5,
                        "parent_id": parent_id,
                        "chunk_role": "child",
                        "parent_index": parent_index,
                        "child_index": child_index,
                    }
                )
                child_docs.append(child_doc)

        return child_docs

    def load_document(self):
        data_root = Path(get_abs_path(chroma_conf["data_path"])).resolve()
        allowed_files_path: tuple[str, ...] = listdir_with_allowed_type(
            str(data_root),
            tuple(chroma_conf["allow_knowledge_file_type"]),
        )
        parent_store = self._load_parent_store()
        chunk_schema_version = chroma_conf.get("chunk_schema_version", "parent_child_v1")

        for path in allowed_files_path:
            file_md5 = get_file_md5_hex(path)

            if not file_md5:
                logger.warning(f"[load_knowledge_base]{path} md5 calculation failed, skipped")
                continue

            md5_for_check = f"{chunk_schema_version}:{file_md5}"

            if self._check_md5_hex(md5_for_check):
                logger.info(f"[load_knowledge_base]{path} already loaded, skipped")
                continue

            try:
                recipe_id = make_node_id(Path(path), data_root)
                documents = self._get_file_documents(path)

                if not documents:
                    logger.warning(f"[load_knowledge_base]{path} has no valid content, skipped")
                    continue

                child_documents = self._build_parent_child_documents(
                    documents=documents,
                    file_md5=file_md5,
                    recipe_id=recipe_id,
                    parent_store=parent_store,
                )

                if not child_documents:
                    logger.warning(f"[load_knowledge_base]{path} has no valid child chunks, skipped")
                    continue

                self.vector_store.add_documents(child_documents)
                self._save_parent_store(parent_store)
                self._save_md5_hex(md5_for_check)

                logger.info(
                    f"[load_knowledge_base]{path} loaded with "
                    f"{len(child_documents)} child chunks"
                )
            except Exception as exc:
                logger.error(f"[load_knowledge_base]{path} load failed: {exc}", exc_info=True)
                continue


if __name__ == "__main__":
    vs = VectorStoreService()
    vs.load_document()

    retriever = vs.get_retriever()
    res = retriever.invoke("番茄和鸡蛋可以做什么菜")

    for r in res:
        print(r.page_content)
        print("-" * 20)
