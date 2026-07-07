# bm25检索模块

import jieba
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document

from graph.graph_data_preparation import GraphDataPreparationModule


class BM25RecipeRetriever:
    def __init__(self) -> None:
        self.documents: list[Document] = []
        self.tokenized_corpus: list[list[str]] = []
        self.bm25: BM25Okapi | None = None
        self._build_index()

    def _tokenize(self, text: str) -> list[str]:
        return [
            token.strip()
            for token in jieba.lcut(text)
            if token.strip()
        ]

    def _build_index(self) -> None:
        graph_data = GraphDataPreparationModule()

        try:
            self.documents = graph_data.load_recipe_documents()
        finally:
            graph_data.close()

        self.tokenized_corpus = [
            self._tokenize(doc.page_content)
            for doc in self.documents
        ]

        self.bm25 = BM25Okapi(self.tokenized_corpus)

    def search(
        self,
        query: str,
        k: int = 10,
        recipe_ids: list[str] | None = None,
    ) -> list[tuple[Document, float]]:
        if self.bm25 is None:
            return []

        query_tokens = self._tokenize(query)
        scores = self.bm25.get_scores(query_tokens)

        results: list[tuple[Document, float]] = []

        allowed_ids = set(recipe_ids or [])

        for doc, score in zip(self.documents, scores):
            recipe_id = doc.metadata.get("recipe_id") or doc.metadata.get("node_id")

            if recipe_ids and recipe_id not in allowed_ids:
                continue

            if score <= 0:
                continue

            results.append((doc, float(score)))

        results.sort(
            key=lambda item: item[1],
            reverse=True,
        )

        return results[:k]