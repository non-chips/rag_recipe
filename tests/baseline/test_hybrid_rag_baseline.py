from __future__ import annotations

import sys
from types import ModuleType

from langchain_core.documents import Document

from fakes import (
    FakeBM25Retriever,
    FakeNeo4jAdapter,
    FakeRetriever,
)


def test_hybrid_retrieval_fuses_graph_vector_and_bm25(
    monkeypatch,
    fresh_import,
) -> None:
    graph_doc = Document(
        page_content="番茄炒蛋图谱上下文",
        metadata={"recipe_id": "recipe-1", "recipe_name": "番茄炒蛋"},
    )
    vector_doc = Document(
        page_content="番茄炒蛋文本步骤",
        metadata={
            "recipe_id": "recipe-1",
            "recipe_name": "番茄炒蛋",
            "source": "番茄炒蛋.md",
        },
    )
    bm25_doc = Document(
        page_content="番茄和鸡蛋",
        metadata={"recipe_id": "recipe-1", "recipe_name": "番茄炒蛋"},
    )
    graph = FakeNeo4jAdapter(
        candidates=[{"recipe_id": "recipe-1", "recipe_name": "番茄炒蛋"}],
        graph_documents=[graph_doc],
        evidence=[
            {
                "recipe_id": "recipe-1",
                "recipe_name": "番茄炒蛋",
                "ingredients": [{"name": "番茄"}, {"name": "鸡蛋"}],
                "tools": ["炒锅"],
                "steps": [],
            }
        ],
    )
    vector_retriever = FakeRetriever([vector_doc])
    bm25_retriever = FakeBM25Retriever([(bm25_doc, 3.0)])

    graph_module = ModuleType("graph.graph_retriever")
    graph_module.GraphRecipeRetriever = lambda: graph
    vector_module = ModuleType("rag.vector_store")

    class _VectorStore:
        def get_retriever(self):
            return vector_retriever

    vector_module.VectorStoreService = _VectorStore
    bm25_module = ModuleType("rag.retrieval.bm25_retriever")
    bm25_module.BM25RecipeRetriever = lambda: bm25_retriever

    monkeypatch.setitem(sys.modules, "graph.graph_retriever", graph_module)
    monkeypatch.setitem(sys.modules, "rag.vector_store", vector_module)
    monkeypatch.setitem(sys.modules, "rag.retrieval.bm25_retriever", bm25_module)

    hybrid_module = fresh_import("rag.hybrid_rag_service")
    service = hybrid_module.HybridRagService()
    result = service.retrieve("我有番茄和鸡蛋", ingredients=["番茄", "鸡蛋"])

    assert result.candidate_recipe_ids == ["recipe-1"]
    assert result.graph_evidence[0]["recipe_name"] == "番茄炒蛋"
    assert result.text_docs[0].metadata["recipe_id"] == "recipe-1"
    assert result.fused_results[0].sources == ["bm25", "chroma", "graph"]
    assert vector_retriever.queries == [("我有番茄和鸡蛋", {"parent_k": 20})]

    service.close()
    assert graph.closed is True
