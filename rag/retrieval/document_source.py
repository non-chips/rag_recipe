"""Injectable recipe document sources used by keyword retrieval."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol, runtime_checkable

from langchain_core.documents import Document

from graph.recipe_parser import parse_recipe_markdown
from rag.ingestion.metadata_normalizer import normalize_metadata


@runtime_checkable
class RecipeDocumentSource(Protocol):
    """Load complete recipe documents for an index builder."""

    def load_documents(self) -> list[Document]:
        """Return a stable snapshot of recipe documents."""


class MarkdownRecipeDocumentSource:
    """Load complete recipe documents directly from the Markdown knowledge base."""

    def __init__(self, data_dir: str | Path | None = None) -> None:
        if data_dir is None:
            from utils.config_handler import chroma_conf
            from utils.path_tool import get_abs_path

            data_dir = get_abs_path(chroma_conf["data_path"])
        self.data_dir = Path(data_dir).resolve()

    def load_documents(self) -> list[Document]:
        if not self.data_dir.is_dir():
            return []

        documents: list[Document] = []
        paths = sorted(
            (*self.data_dir.rglob("*.md"), *self.data_dir.rglob("*.markdown")),
            key=lambda item: str(item).lower(),
        )
        for path in paths:
            content = path.read_text(encoding="utf-8")
            recipe = parse_recipe_markdown(path, self.data_dir)
            content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            metadata = {
                "recipe_id": recipe.node_id,
                "node_id": recipe.node_id,
                "recipe_name": recipe.name,
                "source": str(path),
                "source_path": str(path),
                "category": recipe.category,
                "ingredients": [item.name for item in recipe.ingredients],
                "tools": [item.name for item in recipe.tools],
                "schema_version": "retrieval_metadata_v1",
                "knowledge_version": f"sha256:{content_digest}",
                "doc_type": "markdown_recipe",
            }
            normalized = normalize_metadata(metadata).metadata
            if normalized is not None:
                documents.append(Document(page_content=content, metadata=normalized))

        return documents


class SnapshotRecipeDocumentSource:
    """Expose an already loaded document snapshot through the source protocol."""

    def __init__(self, documents: list[Document]) -> None:
        self._documents = list(documents)

    def load_documents(self) -> list[Document]:
        return list(self._documents)


class Neo4jRecipeDocumentSource:
    """Optional legacy source; importing it does not create a Neo4j connection."""

    def load_documents(self) -> list[Document]:
        from graph.graph_data_preparation import GraphDataPreparationModule

        graph_data = GraphDataPreparationModule()
        try:
            return graph_data.load_recipe_documents()
        finally:
            graph_data.close()
