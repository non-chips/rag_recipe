from __future__ import annotations

from langchain_core.documents import Document

from rag.retrieval.bm25_retriever import BM25RecipeRetriever
from rag.retrieval.document_source import (
    MarkdownRecipeDocumentSource,
    SnapshotRecipeDocumentSource,
)
from recipe_assistant.schemas.retrieval import RetrievalRequest, RetrievalStrategy
from recipe_assistant.services.retrieval import RetrievalService


class _Graph:
    def __init__(self, document: Document) -> None:
        self.document = document

    def hybrid_graph_retrieve(self, **_kwargs):
        recipe_id = self.document.metadata["recipe_id"]
        return {
            "candidate_recipe_ids": [recipe_id],
            "graph_context_docs": [self.document],
        }

    def get_recipe_evidence(self, recipe_ids: list[str]) -> list[dict]:
        return [{"recipe_id": recipe_ids[0], "recipe_name": "番茄炒蛋"}]


class _Vector:
    def __init__(self, document: Document) -> None:
        self.document = document

    def invoke(self, _query: str, **_kwargs) -> list[Document]:
        return [self.document]


def test_markdown_bm25_participates_in_three_way_hybrid_retrieval(tmp_path) -> None:
    recipe_path = tmp_path / "番茄炒蛋.md"
    recipe_path.write_text(
        "# 番茄炒蛋\n\n## 食材\n- 番茄\n- 鸡蛋\n\n## 制作步骤\n- 炒熟鸡蛋和番茄\n",
        encoding="utf-8",
    )
    (tmp_path / "清蒸鲈鱼.md").write_text(
        "# 清蒸鲈鱼\n\n## 食材\n- 鲈鱼\n\n## 制作步骤\n- 蒸熟鲈鱼\n",
        encoding="utf-8",
    )
    (tmp_path / "红烧牛肉.md").write_text(
        "# 红烧牛肉\n\n## 食材\n- 牛肉\n\n## 制作步骤\n- 炖煮牛肉\n",
        encoding="utf-8",
    )
    documents = MarkdownRecipeDocumentSource(tmp_path).load_documents()
    document = next(
        item for item in documents if item.metadata["recipe_name"] == "番茄炒蛋"
    )
    bm25 = BM25RecipeRetriever(SnapshotRecipeDocumentSource(documents))
    service = RetrievalService(
        graph_retriever=_Graph(document),
        vector_retriever=_Vector(document),
        bm25_retriever=bm25,
    )

    result = service.retrieve(
        RetrievalRequest(
            query="番茄",
            strategy=RetrievalStrategy.ADVANCED_HYBRID,
        )
    )

    assert len(result.hits) == 1
    assert result.hits[0].recipe_id == document.metadata["recipe_id"]
    assert result.hits[0].retrieval_sources == ["bm25", "chroma", "graph"]
    assert result.hits[0].bm25_score is not None
    assert result.graph_evidence[0]["recipe_name"] == "番茄炒蛋"
    assert result.fallback_used is False
