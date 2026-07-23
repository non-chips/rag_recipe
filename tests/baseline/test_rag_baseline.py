from __future__ import annotations

from langchain_core.documents import Document

from fakes import FakeRetriever
from recipe_assistant.schemas.retrieval import RetrievalRequest, RetrievalStrategy
from recipe_assistant.services.retrieval import RetrievalService


def test_retrieval_service_returns_vector_evidence_without_answer_facade() -> None:
    documents = [
        Document(
            page_content="白灼虾：水开后放入虾，煮熟后捞出。",
            metadata={
                "recipe_id": "recipe-shrimp",
                "recipe_name": "白灼虾",
                "source_path": "白灼虾.md",
            },
        )
    ]
    retriever = FakeRetriever(documents)
    service = RetrievalService(
        graph_retriever=None,
        vector_retriever=retriever,
        bm25_retriever=None,
    )

    result = service.retrieve(
        RetrievalRequest(
            query="白灼虾怎么做？",
            strategy=RetrievalStrategy.VECTOR_ONLY,
        )
    )

    assert result.hits[0].recipe_id == "recipe-shrimp"
    assert result.hits[0].content == documents[0].page_content
    assert retriever.queries[-1][0] == "白灼虾怎么做？"
