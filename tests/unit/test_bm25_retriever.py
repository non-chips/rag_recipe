from __future__ import annotations

import sys

from langchain_core.documents import Document

from rag.retrieval.bm25_retriever import BM25RecipeRetriever
from rag.retrieval.document_source import (
    MarkdownRecipeDocumentSource,
    SnapshotRecipeDocumentSource,
)


class _CountingSource:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents
        self.load_count = 0

    def load_documents(self) -> list[Document]:
        self.load_count += 1
        return list(self.documents)


def test_bm25_uses_injected_source_once_without_importing_neo4j_source() -> None:
    sys.modules.pop("graph.graph_data_preparation", None)
    source = _CountingSource(
        [
            Document(
                page_content="番茄 鸡蛋 炒锅",
                metadata={"node_id": "recipe-1", "source": "番茄炒蛋.md"},
            ),
            Document(
                page_content="清蒸 鲈鱼 蒸锅",
                metadata={"recipe_id": "recipe-2", "source": "清蒸鲈鱼.md"},
            ),
            Document(
                page_content="红烧 牛肉 砂锅",
                metadata={"recipe_id": "recipe-3", "source": "红烧牛肉.md"},
            ),
        ]
    )

    retriever = BM25RecipeRetriever(document_source=source)
    first = retriever.search("番茄")
    second = retriever.search("番茄")

    assert source.load_count == 1
    assert retriever.index_build_count == 1
    assert first[0][0].metadata["recipe_id"] == "recipe-1"
    assert second
    assert "graph.graph_data_preparation" not in sys.modules


def test_bm25_no_arg_constructor_keeps_compatibility(monkeypatch) -> None:
    source = _CountingSource(
        [Document(page_content="清蒸鱼", metadata={"recipe_id": "recipe-fish"})]
    )
    monkeypatch.setattr(
        "rag.retrieval.bm25_retriever.MarkdownRecipeDocumentSource",
        lambda: source,
    )

    retriever = BM25RecipeRetriever()

    assert retriever.document_source is source
    assert retriever.documents[0].metadata["recipe_id"] == "recipe-fish"


def test_markdown_source_emits_unified_metadata(tmp_path) -> None:
    category_dir = tmp_path / "家常菜"
    category_dir.mkdir()
    recipe_path = category_dir / "番茄炒蛋.md"
    recipe_path.write_text(
        "# 番茄炒蛋\n\n## 食材\n- 番茄\n- 鸡蛋\n\n## 工具\n- 炒锅\n",
        encoding="utf-8",
    )

    documents = MarkdownRecipeDocumentSource(tmp_path).load_documents()

    assert len(documents) == 1
    metadata = documents[0].metadata
    assert metadata["recipe_id"] == metadata["node_id"]
    assert metadata["recipe_name"] == "番茄炒蛋"
    assert metadata["source_path"] == str(recipe_path)
    assert metadata["schema_version"] == "retrieval_metadata_v1"
    assert metadata["knowledge_version"].startswith("sha256:")
    assert isinstance(SnapshotRecipeDocumentSource(documents).load_documents(), list)
