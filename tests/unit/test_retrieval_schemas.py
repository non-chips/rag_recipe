from __future__ import annotations

import pytest
from pydantic import ValidationError

from rag.schemas import RetrievalRequest as LegacyRetrievalRequest
from recipe_assistant.schemas.retrieval import (
    RetrievalHit,
    RetrievalRequest,
    RetrievalResult,
    RetrievalStrategy,
)


def test_retrieval_request_normalizes_filters_and_has_isolated_defaults() -> None:
    first = RetrievalRequest(
        query="  红烧肉  ",
        include_ingredients=[" 猪肉 ", "猪肉", ""],
    )
    second = RetrievalRequest(query="清蒸鱼")

    first.categories.append("家常菜")

    assert first.query == "红烧肉"
    assert first.include_ingredients == ["猪肉"]
    assert second.categories == []


@pytest.mark.parametrize(
    ("payload", "error_fragment"),
    [
        ({"query": "   "}, "String should have at least 1 character"),
        ({"query": "菜谱", "top_k": 10, "candidate_k": 5}, "candidate_k"),
    ],
)
def test_retrieval_request_rejects_invalid_input(
    payload: dict[str, object], error_fragment: str
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        RetrievalRequest.model_validate(payload)

    assert error_fragment in str(exc_info.value)


def test_retrieval_hit_and_result_expose_canonical_contract() -> None:
    hit = RetrievalHit(
        recipe_id="recipe_123",
        recipe_name="红烧肉",
        source_path="data/红烧肉.md",
        content="红烧肉的做法",
        parent_id="parent_1",
        chunk_id="chunk_1",
        knowledge_version="md5:abc",
        retrieval_sources=["vector", "bm25"],
        fused_score=0.8,
    )
    result = RetrievalResult(
        query="红烧肉",
        strategy=RetrievalStrategy.DENSE_BM25,
        hits=[hit],
        confidence=0.7,
    )

    assert result.hits[0].recipe_id == "recipe_123"
    assert result.hits[0].schema_version == "retrieval_metadata_v1"
    assert result.strategy is RetrievalStrategy.DENSE_BM25


def test_legacy_schema_namespace_reexports_canonical_model() -> None:
    assert LegacyRetrievalRequest is RetrievalRequest
