#RRF fusion模块
from dataclasses import dataclass
from langchain_core.documents import Document


@dataclass
class RankedDocument:
    doc_id: str
    document: Document
    score: float
    source: str
    rank: int
    recipe_id: str | None = None
    recipe_name: str | None = None


@dataclass
class FusedDocument:
    doc_id: str
    document: Document
    fused_score: float
    sources: list[str]
    recipe_id: str | None = None
    recipe_name: str | None = None


def make_doc_id(document: Document) -> str:
    recipe_id = (
        document.metadata.get("recipe_id")
        or document.metadata.get("node_id")
        or ""
    )

    chunk_id = document.metadata.get("chunk_id")

    if chunk_id is not None:
        return f"{recipe_id}_{chunk_id}"

    return f"{recipe_id}_{hash(document.page_content[:200])}"


def rrf_fusion(
    ranked_lists: list[list[RankedDocument]],
    k: int = 60,
    top_k: int = 10,
    weights: dict[str, float] | None = None,
) -> list[FusedDocument]:
    weights = weights or {}

    score_map: dict[str, float] = {}
    doc_map: dict[str, Document] = {}
    source_map: dict[str, set[str]] = {}
    recipe_id_map: dict[str, str | None] = {}
    recipe_name_map: dict[str, str | None] = {}

    for ranked_list in ranked_lists:
        for item in ranked_list:
            weight = weights.get(item.source, 1.0)
            score = weight * (1.0 / (k + item.rank))

            score_map[item.doc_id] = score_map.get(item.doc_id, 0.0) + score
            doc_map[item.doc_id] = item.document
            source_map.setdefault(item.doc_id, set()).add(item.source)
            recipe_id_map[item.doc_id] = item.recipe_id
            recipe_name_map[item.doc_id] = item.recipe_name

    fused = [
        FusedDocument(
            doc_id=doc_id,
            document=doc_map[doc_id],
            fused_score=score,
            sources=sorted(source_map.get(doc_id, set())),
            recipe_id=recipe_id_map.get(doc_id),
            recipe_name=recipe_name_map.get(doc_id),
        )
        for doc_id, score in score_map.items()
    ]

    fused.sort(
        key=lambda item: item.fused_score,
        reverse=True,
    )

    return fused[:top_k]