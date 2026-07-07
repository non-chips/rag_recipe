from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from graph.graph_retriever import GraphRecipeRetriever
from rag.retrieval.bm25_retriever import BM25RecipeRetriever
from rag.retrieval.fusion import FusedDocument, RankedDocument, rrf_fusion
from rag.vector_store import VectorStoreService
from utils.config_handler import chroma_conf


HYBRID_PROMPT = """
你是一个菜谱知识库助手。
请严格依据下面的“图谱结构化依据”和“菜谱文本上下文”回答用户问题。

回答要求：
1. 优先给出满足条件的菜名。
2. 说明为什么这些菜满足用户条件，图谱依据优先用于食材、工具、分类、难度等结构化判断。
3. 做法、步骤、用量等细节必须来自菜谱文本上下文，不要编造。
4. 如果图谱依据或文本上下文不足，请明确说明当前知识库中没有找到足够信息。
5. 仅使用中文回答，结尾简要标注来源菜谱。

用户问题：
{input}

图谱结构化依据：
{graph_context}

菜谱文本上下文：
{text_context}
"""


@dataclass
class HybridRetrievalResult:
    query: str
    filters: dict[str, Any]
    candidates: list[dict]
    graph_evidence: list[dict]
    text_docs: list[Document]
    graph_context_docs: list[Document] = field(default_factory=list)
    fused_results: list[FusedDocument] = field(default_factory=list)

    @property
    def candidate_recipe_ids(self) -> list[str]:
        return [
            item["recipe_id"]
            for item in self.candidates
            if item.get("recipe_id")
        ]


class HybridRagService:
    def __init__(self) -> None:
        self.graph_retriever = GraphRecipeRetriever()
        self.vector_store = VectorStoreService()
        self.retriever = self.vector_store.get_retriever()
        self.bm25_retriever = BM25RecipeRetriever()
        self.prompt_template = PromptTemplate.from_template(HYBRID_PROMPT)
        self.chain = None

    def retrieve(
        self,
        query: str,
        ingredients: list[str] | None = None,
        tools: list[str] | None = None,
        category: str | None = None,
        recipe_names: list[str] | None = None,
        candidate_limit: int | None = None,
    ) -> HybridRetrievalResult:
        graph_result = self.graph_retriever.hybrid_graph_retrieve(
            query=query,
            ingredients=ingredients,
            tools=tools,
            category=category,
            recipe_names=recipe_names,
            limit=candidate_limit or chroma_conf.get("hybrid_candidate_limit", 500),
        )

        candidates = graph_result["candidates"]
        candidate_recipe_ids = graph_result["candidate_recipe_ids"]
        graph_context_docs = graph_result["graph_context_docs"]

        chroma_docs = self.retriever.invoke(
            query,
            parent_k=chroma_conf.get("chroma_k", 20),
        )
        bm25_results = self.bm25_retriever.search(
            query=query,
            k=chroma_conf.get("bm25_k", 20),
        )
        bm25_docs = [
            doc
            for doc, _score in bm25_results
        ]

        fused_results = self._fuse_three_way(
            graph_context_docs=graph_context_docs,
            chroma_docs=chroma_docs,
            bm25_docs=bm25_docs,
            candidate_recipe_ids=candidate_recipe_ids,
        )

        ranked_recipe_ids = [
            item.recipe_id
            for item in fused_results
            if item.recipe_id
        ]
        if not ranked_recipe_ids:
            ranked_recipe_ids = candidate_recipe_ids[: chroma_conf.get("k", 5)]

        graph_evidence = self.graph_retriever.get_recipe_evidence(ranked_recipe_ids)
        text_docs = self._select_text_docs_for_fused_results(
            fused_results=fused_results,
            chroma_docs=chroma_docs,
            bm25_docs=bm25_docs,
            graph_context_docs=graph_context_docs,
        )

        return HybridRetrievalResult(
            query=query,
            filters=graph_result["filters"],
            candidates=candidates,
            graph_evidence=graph_evidence,
            text_docs=text_docs,
            graph_context_docs=graph_context_docs,
            fused_results=fused_results,
        )

    def hybrid_summarize(
        self,
        query: str,
        ingredients: list[str] | None = None,
        tools: list[str] | None = None,
        category: str | None = None,
        recipe_names: list[str] | None = None,
    ) -> str:
        result = self.retrieve(
            query=query,
            ingredients=ingredients,
            tools=tools,
            category=category,
            recipe_names=recipe_names,
        )

        if not result.candidates and not result.text_docs:
            return "当前菜谱知识库中没有找到足够信息。"

        return self._get_chain().invoke(
            {
                "input": query,
                "graph_context": self._format_graph_context(result.graph_evidence),
                "text_context": self._format_text_context(result.text_docs),
            }
        )

    def close(self) -> None:
        self.graph_retriever.close()

    def _fuse_three_way(
        self,
        graph_context_docs: list[Document],
        chroma_docs: list[Document],
        bm25_docs: list[Document],
        candidate_recipe_ids: list[str],
    ) -> list[FusedDocument]:
        graph_ranked = self._to_ranked_documents(
            docs=graph_context_docs,
            source="graph",
            candidate_recipe_ids=candidate_recipe_ids,
        )
        chroma_ranked = self._to_ranked_documents(
            docs=chroma_docs,
            source="chroma",
            candidate_recipe_ids=candidate_recipe_ids,
        )
        bm25_ranked = self._to_ranked_documents(
            docs=bm25_docs,
            source="bm25",
            candidate_recipe_ids=candidate_recipe_ids,
        )

        return rrf_fusion(
            ranked_lists=[
                graph_ranked,
                chroma_ranked,
                bm25_ranked,
            ],
            k=chroma_conf.get("rrf_k", 60),
            top_k=chroma_conf.get("k", 5),
            weights=chroma_conf.get(
                "rrf_weights",
                {
                    "graph": 1.2,
                    "chroma": 1.0,
                    "bm25": 0.9,
                },
            ),
        )

    def _to_ranked_documents(
        self,
        docs: list[Document],
        source: str,
        candidate_recipe_ids: list[str],
    ) -> list[RankedDocument]:
        candidate_set = set(candidate_recipe_ids)
        ranked_docs: list[RankedDocument] = []
        seen_recipe_ids: set[str] = set()

        for doc in docs:
            recipe_id = doc.metadata.get("recipe_id") or doc.metadata.get("node_id")
            if not recipe_id or recipe_id in seen_recipe_ids:
                continue

            seen_recipe_ids.add(str(recipe_id))
            rank = len(ranked_docs) + 1

            if source != "graph" and recipe_id in candidate_set:
                rank = max(1, rank - 3)

            ranked_docs.append(
                RankedDocument(
                    doc_id=str(recipe_id),
                    document=doc,
                    score=1.0 / rank,
                    source=source,
                    rank=rank,
                    recipe_id=str(recipe_id),
                    recipe_name=doc.metadata.get("recipe_name"),
                )
            )

        return ranked_docs

    def _select_text_docs_for_fused_results(
        self,
        fused_results: list[FusedDocument],
        chroma_docs: list[Document],
        bm25_docs: list[Document],
        graph_context_docs: list[Document],
    ) -> list[Document]:
        chroma_by_recipe_id = self._first_doc_by_recipe_id(chroma_docs)
        bm25_by_recipe_id = self._first_doc_by_recipe_id(bm25_docs)
        graph_by_recipe_id = self._first_doc_by_recipe_id(graph_context_docs)

        selected_docs: list[Document] = []
        for item in fused_results:
            if not item.recipe_id:
                continue

            doc = (
                chroma_by_recipe_id.get(item.recipe_id)
                or bm25_by_recipe_id.get(item.recipe_id)
                or graph_by_recipe_id.get(item.recipe_id)
            )
            if doc:
                doc.metadata["fusion_score"] = item.fused_score
                doc.metadata["fusion_sources"] = item.sources
                selected_docs.append(doc)

        return selected_docs

    def _first_doc_by_recipe_id(self, docs: list[Document]) -> dict[str, Document]:
        doc_map: dict[str, Document] = {}

        for doc in docs:
            recipe_id = doc.metadata.get("recipe_id") or doc.metadata.get("node_id")
            if recipe_id and str(recipe_id) not in doc_map:
                doc_map[str(recipe_id)] = doc

        return doc_map

    def _get_chain(self):
        if self.chain is None:
            from model.factory import chat_model

            self.chain = self.prompt_template | chat_model | StrOutputParser()

        return self.chain

    def _format_graph_context(self, rows: list[dict]) -> str:
        if not rows:
            return "无图谱依据。"

        lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            ingredients = self._format_ingredients(row.get("ingredients") or [])
            tools = "、".join(row.get("tools") or [])
            steps = sorted(
                row.get("steps") or [],
                key=lambda item: item.get("step_number") or 0,
            )
            step_text = "；".join(
                [
                    f"{step.get('step_number')}. {step.get('description') or step.get('name')}"
                    for step in steps[:5]
                    if step.get("description") or step.get("name")
                ]
            )

            lines.append(
                "\n".join(
                    [
                        f"[图谱依据{index}]",
                        f"菜谱ID：{row.get('recipe_id')}",
                        f"菜名：{row.get('recipe_name')}",
                        f"分类：{row.get('category')}",
                        f"难度：{row.get('difficulty')}",
                        f"食材：{ingredients or '无'}",
                        f"工具：{tools or '无'}",
                        f"步骤摘要：{step_text or '无'}",
                        f"来源：{row.get('source')}",
                    ]
                )
            )

        return "\n\n".join(lines)

    def _format_ingredients(self, ingredients: list[dict]) -> str:
        parts: list[str] = []
        for item in ingredients:
            name = item.get("name")
            if not name:
                continue

            amount = item.get("amount")
            unit = item.get("unit")
            raw_text = item.get("raw_text")
            if amount or unit:
                parts.append(f"{name}({amount or ''}{unit or ''})")
            elif raw_text:
                parts.append(str(raw_text))
            else:
                parts.append(str(name))

        return "、".join(parts)

    def _format_text_context(self, docs: list[Document]) -> str:
        if not docs:
            return "无文本上下文。"

        lines: list[str] = []
        for index, doc in enumerate(docs, start=1):
            lines.append(
                "\n".join(
                    [
                        f"[文本上下文{index}]",
                        f"菜谱ID：{doc.metadata.get('recipe_id') or doc.metadata.get('node_id')}",
                        f"融合来源：{doc.metadata.get('fusion_sources')}",
                        f"融合分数：{doc.metadata.get('fusion_score')}",
                        f"来源：{doc.metadata.get('source')}",
                        doc.page_content,
                    ]
                )
            )

        return "\n\n".join(lines)
