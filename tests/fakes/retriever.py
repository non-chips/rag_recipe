from __future__ import annotations

from langchain_core.documents import Document


class FakeRetriever:
    """In-memory replacement for vector and parent-child retrievers."""

    def __init__(self, documents: list[Document] | None = None) -> None:
        self.documents = list(documents or [])
        self.queries: list[tuple[str, dict]] = []

    def invoke(self, query: str, **kwargs) -> list[Document]:
        self.queries.append((query, kwargs))
        return list(self.documents)


class FakeVectorStoreService:
    """Minimal replacement for VectorStoreService."""

    def __init__(self, documents: list[Document] | None = None) -> None:
        self.retriever = FakeRetriever(documents)

    def get_retriever(self) -> FakeRetriever:
        return self.retriever


class FakeBM25Retriever:
    """Deterministic replacement for BM25RecipeRetriever."""

    def __init__(self, results: list[tuple[Document, float]] | None = None) -> None:
        self.results = list(results or [])
        self.queries: list[tuple[str, int, list[str] | None]] = []

    def search(
        self,
        query: str,
        k: int = 10,
        recipe_ids: list[str] | None = None,
    ) -> list[tuple[Document, float]]:
        self.queries.append((query, k, recipe_ids))
        return list(self.results[:k])
