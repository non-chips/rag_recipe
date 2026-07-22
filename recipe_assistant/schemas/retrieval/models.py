"""Canonical request and response models for recipe retrieval."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RETRIEVAL_METADATA_SCHEMA_VERSION = "retrieval_metadata_v1"
UNVERSIONED_KNOWLEDGE = "unversioned"


class RetrievalStrategy(str, Enum):
    """Retrieval strategies exposed at the service boundary."""

    GRAPH_ONLY = "graph_only"
    VECTOR_ONLY = "vector_only"
    BM25_KEYWORD = "bm25_keyword"
    DENSE_BM25 = "dense_bm25"
    ADVANCED_HYBRID = "advanced_hybrid"


class RetrievalRequest(BaseModel):
    """Structured input accepted by a retrieval service."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1)
    strategy: RetrievalStrategy | None = None
    recipe_names: list[str] = Field(default_factory=list)
    include_ingredients: list[str] = Field(default_factory=list)
    exclude_ingredients: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=100)
    candidate_k: int = Field(default=20, ge=1, le=1000)

    @field_validator(
        "recipe_names",
        "include_ingredients",
        "exclude_ingredients",
        "tools",
        "categories",
    )
    @classmethod
    def remove_empty_filters(cls, values: list[str]) -> list[str]:
        """Normalize list filters while retaining their input order."""

        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_candidate_count(self) -> "RetrievalRequest":
        """Require the candidate pool to cover the requested result count."""

        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be greater than or equal to top_k")
        return self


class NormalizedRetrievalMetadata(BaseModel):
    """Canonical metadata shared by Graph, Chroma and BM25 documents."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recipe_id: str = Field(min_length=1)
    recipe_name: str | None = None
    source_path: str = ""
    parent_id: str | None = None
    chunk_id: str | None = None
    schema_version: str = Field(default=RETRIEVAL_METADATA_SCHEMA_VERSION, min_length=1)
    knowledge_version: str = Field(default=UNVERSIONED_KNOWLEDGE, min_length=1)
    category: str | None = None
    ingredients: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class RetrievalHit(BaseModel):
    """A normalized recipe or recipe chunk returned by retrieval."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recipe_id: str = Field(min_length=1)
    recipe_name: str | None = None
    source_path: str = ""
    content: str = Field(min_length=1)
    parent_id: str | None = None
    chunk_id: str | None = None
    schema_version: str = Field(default=RETRIEVAL_METADATA_SCHEMA_VERSION, min_length=1)
    knowledge_version: str = Field(default=UNVERSIONED_KNOWLEDGE, min_length=1)
    retrieval_sources: list[str] = Field(default_factory=list)
    vector_score: float | None = None
    bm25_score: float | None = None
    graph_score: float | None = None
    rerank_score: float | None = None
    fused_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """Structured retrieval output before answer generation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1)
    strategy: RetrievalStrategy
    hits: list[RetrievalHit] = Field(default_factory=list)
    graph_evidence: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    latency_ms: float = Field(default=0.0, ge=0.0)
    fallback_used: bool = False
