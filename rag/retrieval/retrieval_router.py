"""Technical retrieval strategy routing, independent of business query routing."""

from __future__ import annotations

from recipe_assistant.schemas.retrieval import RetrievalRequest, RetrievalStrategy


class RetrievalRouter:
    """Resolve a request to a fixed set of retrieval backends."""

    _SOURCES: dict[RetrievalStrategy, tuple[str, ...]] = {
        RetrievalStrategy.GRAPH_ONLY: ("graph",),
        RetrievalStrategy.VECTOR_ONLY: ("chroma",),
        RetrievalStrategy.BM25_KEYWORD: ("bm25",),
        RetrievalStrategy.DENSE_BM25: ("chroma", "bm25"),
        RetrievalStrategy.ADVANCED_HYBRID: ("graph", "chroma", "bm25"),
    }

    def __init__(
        self,
        default_strategy: RetrievalStrategy = RetrievalStrategy.ADVANCED_HYBRID,
    ) -> None:
        self.default_strategy = default_strategy

    def route(self, request: RetrievalRequest) -> RetrievalStrategy:
        """Use an explicit strategy or the configured technical default."""

        return request.strategy or self.default_strategy

    def sources_for(self, strategy: RetrievalStrategy) -> tuple[str, ...]:
        """Return backend names for a resolved strategy."""

        return self._SOURCES[strategy]
