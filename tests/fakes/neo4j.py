from __future__ import annotations

from langchain_core.documents import Document


class FakeNeo4jAdapter:
    """In-memory replacement for GraphRecipeRetriever/Neo4j access."""

    def __init__(
        self,
        candidates: list[dict] | None = None,
        graph_documents: list[Document] | None = None,
        evidence: list[dict] | None = None,
    ) -> None:
        self.candidates = list(candidates or [])
        self.graph_documents = list(graph_documents or [])
        self.evidence = list(evidence or [])
        self.closed = False

    def hybrid_graph_retrieve(self, query: str, **filters) -> dict:
        candidate_ids = [
            item["recipe_id"]
            for item in self.candidates
            if item.get("recipe_id")
        ]
        return {
            "filters": {
                "query": query,
                "ingredients": filters.get("ingredients") or [],
                "tools": filters.get("tools") or [],
                "category": filters.get("category"),
                "recipe_names": filters.get("recipe_names") or [],
            },
            "candidates": list(self.candidates),
            "candidate_recipe_ids": candidate_ids,
            "graph_context_docs": list(self.graph_documents),
        }

    def get_recipe_evidence(self, recipe_ids: list[str]) -> list[dict]:
        allowed = set(recipe_ids)
        return [
            item
            for item in self.evidence
            if item.get("recipe_id") in allowed
        ]

    def close(self) -> None:
        self.closed = True
