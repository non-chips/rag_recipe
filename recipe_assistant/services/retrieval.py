"""Retrieval orchestration separated from recipe answer generation."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from langchain_core.documents import Document

from rag.ingestion.metadata_normalizer import MissingRecipeIdPolicy, normalize_metadata
from rag.retrieval.fusion import FusedDocument, RankedDocument, rrf_fusion
from rag.retrieval.retrieval_router import RetrievalRouter
from recipe_assistant.core.config import get_settings
from recipe_assistant.schemas.retrieval import (
    RetrievalHit,
    RetrievalRequest,
    RetrievalResult,
    RetrievalStrategy,
)


_UNSET = object()


@dataclass(slots=True)
class _SourceResult:
    documents: list[Document]
    scores: dict[str, float]
    candidate_recipe_ids: list[str]


class RetrievalService:
    """Reuse retrieval backends and return a normalized retrieval-only result."""

    def __init__(
        self,
        *,
        graph_retriever: Any = _UNSET,
        vector_retriever: Any = _UNSET,
        bm25_retriever: Any = _UNSET,
        router: RetrievalRouter | None = None,
    ) -> None:
        self.router = router or RetrievalRouter()
        self._initialization_errors: dict[str, str] = {}
        self.graph_retriever = self._resolve_graph(graph_retriever)
        self.vector_retriever = self._resolve_vector(vector_retriever)
        self.bm25_retriever = self._resolve_bm25(bm25_retriever)

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        """Run the selected backends, degrade explicitly, and fuse their hits."""

        started_at = perf_counter()
        strategy = self.router.route(request)
        warnings: list[str] = []
        ranked_lists: list[list[RankedDocument]] = []
        scores_by_source: dict[str, dict[str, float]] = {}
        candidate_recipe_ids: list[str] = []

        for source in self.router.sources_for(strategy):
            try:
                source_result = self._retrieve_source(source, request)
            except Exception as exc:
                warnings.append(f"{source} retrieval failed: {exc}")
                continue

            scores_by_source[source] = source_result.scores
            if source == "graph":
                candidate_recipe_ids = source_result.candidate_recipe_ids
            ranked, normalization_warnings = self._rank_documents(
                source_result.documents,
                source,
                candidate_recipe_ids,
            )
            warnings.extend(normalization_warnings)
            if ranked:
                ranked_lists.append(ranked)

        fused = rrf_fusion(
            ranked_lists=ranked_lists,
            top_k=request.top_k,
            weights={"graph": 1.2, "chroma": 1.0, "bm25": 0.9},
        )
        hits = [
            self._to_hit(item, scores_by_source)
            for item in fused
        ]
        graph_evidence = self._load_graph_evidence(
            hits,
            candidate_recipe_ids,
            strategy,
            warnings,
        )
        confidence = self._confidence(hits)

        return RetrievalResult(
            query=request.query,
            strategy=strategy,
            hits=hits,
            graph_evidence=graph_evidence,
            confidence=confidence,
            warnings=warnings,
            latency_ms=(perf_counter() - started_at) * 1000,
            fallback_used=bool(warnings),
        )

    def close(self) -> None:
        """Close owned compatible resources without rebuilding them."""

        seen: set[int] = set()
        for resource in (self.graph_retriever, self.vector_retriever, self.bm25_retriever):
            if resource is None or id(resource) in seen:
                continue
            seen.add(id(resource))
            close = getattr(resource, "close", None)
            if callable(close):
                close()

    def _resolve_graph(self, value: Any) -> Any:
        if value is not _UNSET:
            return value
        if not get_settings().neo4j_enabled:
            self._initialization_errors["graph"] = "disabled by NEO4J_ENABLED"
            return None
        try:
            from graph.graph_retriever import GraphRecipeRetriever

            return GraphRecipeRetriever()
        except Exception as exc:
            self._initialization_errors["graph"] = str(exc)
            return None

    def _resolve_vector(self, value: Any) -> Any:
        if value is not _UNSET:
            return value
        if not get_settings().chroma_enabled:
            self._initialization_errors["chroma"] = "disabled by CHROMA_ENABLED"
            return None
        try:
            from rag.vector_store import VectorStoreService

            return VectorStoreService().get_retriever()
        except Exception as exc:
            self._initialization_errors["chroma"] = str(exc)
            return None

    def _resolve_bm25(self, value: Any) -> Any:
        if value is not _UNSET:
            return value
        if not get_settings().bm25_enabled:
            self._initialization_errors["bm25"] = "disabled by BM25_ENABLED"
            return None
        try:
            from rag.retrieval.bm25_retriever import BM25RecipeRetriever

            return BM25RecipeRetriever()
        except Exception as exc:
            self._initialization_errors["bm25"] = str(exc)
            return None

    def _retrieve_source(self, source: str, request: RetrievalRequest) -> _SourceResult:
        backend = {
            "graph": self.graph_retriever,
            "chroma": self.vector_retriever,
            "bm25": self.bm25_retriever,
        }[source]
        if backend is None:
            reason = self._initialization_errors.get(source, "not configured")
            raise RuntimeError(reason)

        if source == "graph":
            category = request.categories[0] if request.categories else None
            result = backend.hybrid_graph_retrieve(
                query=request.query,
                ingredients=request.include_ingredients,
                tools=request.tools,
                category=category,
                recipe_names=request.recipe_names,
                limit=request.candidate_k,
            )
            return _SourceResult(
                documents=list(result.get("graph_context_docs") or []),
                scores={},
                candidate_recipe_ids=list(result.get("candidate_recipe_ids") or []),
            )

        if source == "chroma":
            documents = list(backend.invoke(request.query, parent_k=request.candidate_k))
            return _SourceResult(documents=documents, scores={}, candidate_recipe_ids=[])

        rows = list(backend.search(query=request.query, k=request.candidate_k))
        scores = {
            str(doc.metadata.get("recipe_id") or doc.metadata.get("node_id")): float(score)
            for doc, score in rows
            if doc.metadata.get("recipe_id") or doc.metadata.get("node_id")
        }
        return _SourceResult(
            documents=[doc for doc, _score in rows],
            scores=scores,
            candidate_recipe_ids=[],
        )

    def _rank_documents(
        self,
        documents: list[Document],
        source: str,
        candidate_recipe_ids: list[str],
    ) -> tuple[list[RankedDocument], list[str]]:
        candidate_set = set(candidate_recipe_ids)
        ranked: list[RankedDocument] = []
        warnings: list[str] = []
        seen: set[str] = set()

        for document in documents:
            outcome = normalize_metadata(
                document.metadata,
                missing_recipe_id=MissingRecipeIdPolicy.SKIP,
            )
            warnings.extend(outcome.warnings)
            if outcome.metadata is None:
                continue
            recipe_id = str(outcome.metadata["recipe_id"])
            if recipe_id in seen:
                continue
            seen.add(recipe_id)
            rank = len(ranked) + 1
            if source != "graph" and recipe_id in candidate_set:
                rank = max(1, rank - 3)
            ranked.append(
                RankedDocument(
                    doc_id=recipe_id,
                    document=document,
                    score=1.0 / rank,
                    source=source,
                    rank=rank,
                    recipe_id=recipe_id,
                    recipe_name=outcome.metadata.get("recipe_name"),
                )
            )

        return ranked, warnings

    def _to_hit(
        self,
        fused: FusedDocument,
        scores_by_source: dict[str, dict[str, float]],
    ) -> RetrievalHit:
        outcome = normalize_metadata(fused.document.metadata)
        if outcome.metadata is None:
            raise RuntimeError("fused document metadata could not be normalized")
        metadata = outcome.metadata
        recipe_id = str(metadata["recipe_id"])
        return RetrievalHit(
            recipe_id=recipe_id,
            recipe_name=metadata.get("recipe_name") or fused.recipe_name,
            source_path=metadata.get("source_path") or "",
            content=fused.document.page_content,
            parent_id=metadata.get("parent_id"),
            chunk_id=metadata.get("chunk_id"),
            schema_version=metadata["schema_version"],
            knowledge_version=metadata["knowledge_version"],
            retrieval_sources=fused.sources,
            bm25_score=scores_by_source.get("bm25", {}).get(recipe_id),
            fused_score=fused.fused_score,
            metadata=dict(fused.document.metadata),
        )

    def _load_graph_evidence(
        self,
        hits: list[RetrievalHit],
        candidate_recipe_ids: list[str],
        strategy: RetrievalStrategy,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        if "graph" not in self.router.sources_for(strategy) or self.graph_retriever is None:
            return []
        recipe_ids = [hit.recipe_id for hit in hits] or candidate_recipe_ids
        if not recipe_ids:
            return []
        try:
            return list(self.graph_retriever.get_recipe_evidence(recipe_ids))
        except Exception as exc:
            warnings.append(f"graph evidence retrieval failed: {exc}")
            return []

    @staticmethod
    def _confidence(hits: list[RetrievalHit]) -> float:
        if not hits:
            return 0.0
        return min(1.0, len(hits[0].retrieval_sources) / 3.0)
