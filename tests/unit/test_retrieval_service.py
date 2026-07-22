from __future__ import annotations

from langchain_core.documents import Document

from recipe_assistant.schemas.retrieval import RetrievalRequest, RetrievalStrategy
from recipe_assistant.services.retrieval import RetrievalService


def _document(recipe_id: str = "recipe-1", content: str = "番茄炒蛋") -> Document:
    return Document(
        page_content=content,
        metadata={
            "recipe_id": recipe_id,
            "recipe_name": "番茄炒蛋",
            "source": "番茄炒蛋.md",
        },
    )


class _GraphBackend:
    instances = 0

    def __init__(self, *, fail: bool = False) -> None:
        type(self).instances += 1
        self.fail = fail
        self.retrieve_calls = 0
        self.evidence_calls = 0
        self.closed = False

    def hybrid_graph_retrieve(self, **_kwargs):
        self.retrieve_calls += 1
        if self.fail:
            raise ConnectionError("graph unavailable")
        return {
            "candidate_recipe_ids": ["recipe-1"],
            "graph_context_docs": [_document(content="图谱上下文")],
        }

    def get_recipe_evidence(self, recipe_ids: list[str]) -> list[dict]:
        self.evidence_calls += 1
        return [{"recipe_id": recipe_ids[0], "recipe_name": "番茄炒蛋"}]

    def close(self) -> None:
        self.closed = True


class _VectorBackend:
    instances = 0

    def __init__(self, *, fail: bool = False) -> None:
        type(self).instances += 1
        self.fail = fail
        self.calls = 0

    def invoke(self, _query: str, **_kwargs) -> list[Document]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("vector unavailable")
        return [_document(content="向量菜谱正文")]


class _BM25Backend:
    instances = 0

    def __init__(self, *, fail: bool = False) -> None:
        type(self).instances += 1
        self.fail = fail
        self.calls = 0

    def search(self, **_kwargs) -> list[tuple[Document, float]]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("bm25 unavailable")
        return [(_document(content="关键词菜谱正文"), 3.5)]


def test_retrieval_service_reuses_backends_across_calls() -> None:
    _GraphBackend.instances = 0
    _VectorBackend.instances = 0
    _BM25Backend.instances = 0
    graph = _GraphBackend()
    vector = _VectorBackend()
    bm25 = _BM25Backend()
    service = RetrievalService(
        graph_retriever=graph,
        vector_retriever=vector,
        bm25_retriever=bm25,
    )
    request = RetrievalRequest(
        query="番茄和鸡蛋怎么做",
        strategy=RetrievalStrategy.ADVANCED_HYBRID,
    )

    first = service.retrieve(request)
    second = service.retrieve(request)

    assert _GraphBackend.instances == 1
    assert _VectorBackend.instances == 1
    assert _BM25Backend.instances == 1
    assert graph.retrieve_calls == vector.calls == bm25.calls == 2
    assert first.hits[0].retrieval_sources == ["bm25", "chroma", "graph"]
    assert second.hits[0].recipe_id == "recipe-1"

    service.close()
    assert graph.closed is True


def test_explicit_strategy_does_not_use_business_query_routing() -> None:
    graph = _GraphBackend()
    vector = _VectorBackend()
    bm25 = _BM25Backend()
    service = RetrievalService(
        graph_retriever=graph,
        vector_retriever=vector,
        bm25_retriever=bm25,
    )

    result = service.retrieve(
        RetrievalRequest(
            query="需要哪些食材",
            strategy=RetrievalStrategy.VECTOR_ONLY,
        )
    )

    assert result.strategy is RetrievalStrategy.VECTOR_ONLY
    assert vector.calls == 1
    assert graph.retrieve_calls == 0
    assert bm25.calls == 0


def test_hybrid_retrieval_degrades_when_graph_and_bm25_fail() -> None:
    service = RetrievalService(
        graph_retriever=_GraphBackend(fail=True),
        vector_retriever=_VectorBackend(),
        bm25_retriever=_BM25Backend(fail=True),
    )

    result = service.retrieve(
        RetrievalRequest(
            query="番茄炒蛋",
            strategy=RetrievalStrategy.ADVANCED_HYBRID,
        )
    )

    assert [hit.recipe_id for hit in result.hits] == ["recipe-1"]
    assert result.hits[0].retrieval_sources == ["chroma"]
    assert result.fallback_used is True
    assert any("graph retrieval failed" in warning for warning in result.warnings)
    assert any("bm25 retrieval failed" in warning for warning in result.warnings)


def test_hybrid_retrieval_degrades_when_vector_fails() -> None:
    service = RetrievalService(
        graph_retriever=_GraphBackend(),
        vector_retriever=_VectorBackend(fail=True),
        bm25_retriever=_BM25Backend(),
    )

    result = service.retrieve(
        RetrievalRequest(
            query="番茄炒蛋",
            strategy=RetrievalStrategy.ADVANCED_HYBRID,
        )
    )

    assert result.hits[0].retrieval_sources == ["bm25", "graph"]
    assert result.fallback_used is True
    assert any("chroma retrieval failed" in warning for warning in result.warnings)
