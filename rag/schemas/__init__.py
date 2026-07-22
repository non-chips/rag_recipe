"""Legacy namespace for retrieval schema consumers."""

from .retrieval import (
    RETRIEVAL_METADATA_SCHEMA_VERSION,
    UNVERSIONED_KNOWLEDGE,
    NormalizedRetrievalMetadata,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResult,
    RetrievalStrategy,
)

__all__ = [
    "RETRIEVAL_METADATA_SCHEMA_VERSION",
    "UNVERSIONED_KNOWLEDGE",
    "NormalizedRetrievalMetadata",
    "RetrievalHit",
    "RetrievalRequest",
    "RetrievalResult",
    "RetrievalStrategy",
]
