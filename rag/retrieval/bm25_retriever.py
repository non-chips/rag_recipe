from langchain_core.documents import Document
import jieba
from rank_bm25 import BM25Okapi

from rag.ingestion.metadata_normalizer import MissingRecipeIdPolicy, normalize_metadata
from rag.retrieval.document_source import MarkdownRecipeDocumentSource, RecipeDocumentSource


class BM25RecipeRetriever:
    """Reusable BM25 index over an injectable recipe document source."""

    def __init__(self, document_source: RecipeDocumentSource | None = None) -> None:
        self.document_source = document_source or MarkdownRecipeDocumentSource()
        self.documents: list[Document] = []
        self.tokenized_corpus: list[list[str]] = []
        self.bm25: BM25Okapi | None = None
        self.normalization_warnings: list[str] = []
        self.index_build_count = 0
        self._build_index()

    def _tokenize(self, text: str) -> list[str]:
        return [
            token.strip()
            for token in jieba.lcut(text)
            if token.strip()
        ]

    def _build_index(self) -> None:
        """Build one index from the configured source snapshot."""

        self.index_build_count += 1
        self.documents = []
        self.normalization_warnings = []
        for document in self.document_source.load_documents():
            outcome = normalize_metadata(
                document.metadata,
                missing_recipe_id=MissingRecipeIdPolicy.SKIP,
            )
            self.normalization_warnings.extend(outcome.warnings)
            if outcome.metadata is None:
                continue
            self.documents.append(
                Document(page_content=document.page_content, metadata=outcome.metadata)
            )

        self.tokenized_corpus = [
            self._tokenize(doc.page_content)
            for doc in self.documents
        ]
        self.bm25 = BM25Okapi(self.tokenized_corpus) if self.tokenized_corpus else None

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
