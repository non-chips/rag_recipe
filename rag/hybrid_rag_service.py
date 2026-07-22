from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from graph.graph_retriever import GraphRecipeRetriever
from rag.retrieval.bm25_retriever import BM25RecipeRetriever
from rag.retrieval.fusion import FusedDocument
from rag.vector_store import VectorStoreService
from recipe_assistant.schemas.retrieval import RetrievalRequest, RetrievalStrategy
from recipe_assistant.services.retrieval import RetrievalService
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
        # 初始化检索服务
        self.graph_retriever = GraphRecipeRetriever()
        self.vector_store = VectorStoreService()
        self.retriever = self.vector_store.get_retriever()
        self.bm25_retriever = BM25RecipeRetriever()
        self.retrieval_service = RetrievalService(
            graph_retriever=self.graph_retriever,
            vector_retriever=self.retriever,
            bm25_retriever=self.bm25_retriever,
        )
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
        request = RetrievalRequest(
            query=query,
            strategy=RetrievalStrategy.ADVANCED_HYBRID,
            include_ingredients=ingredients or [],
            tools=tools or [],
            categories=[category] if category else [],
            recipe_names=recipe_names or [],
            top_k=chroma_conf.get("k", 5),
            candidate_k=candidate_limit or chroma_conf.get("chroma_k", 20),
        )
        retrieval_result = self.retrieval_service.retrieve(request)

        text_docs: list[Document] = []
        fused_results: list[FusedDocument] = []
        for hit in retrieval_result.hits:
            metadata = dict(hit.metadata)
            metadata.setdefault("recipe_id", hit.recipe_id)
            metadata.setdefault("recipe_name", hit.recipe_name)
            metadata.setdefault("source_path", hit.source_path)
            metadata["fusion_score"] = hit.fused_score
            metadata["fusion_sources"] = hit.retrieval_sources
            document = Document(page_content=hit.content, metadata=metadata)
            text_docs.append(document)
            fused_results.append(
                FusedDocument(
                    doc_id=hit.recipe_id,
                    document=document,
                    fused_score=hit.fused_score,
                    sources=hit.retrieval_sources,
                    recipe_id=hit.recipe_id,
                    recipe_name=hit.recipe_name,
                )
            )

        candidates = [
            {
                "recipe_id": row.get("recipe_id"),
                "recipe_name": row.get("recipe_name"),
            }
            for row in retrieval_result.graph_evidence
            if row.get("recipe_id")
        ]
        filters = {
            "ingredients": ingredients or [],
            "tools": tools or [],
            "category": category,
            "recipe_names": recipe_names or [],
        }
        graph_context_docs = [
            Document(
                page_content=self._format_graph_context([row]),
                metadata={
                    "recipe_id": row.get("recipe_id"),
                    "node_id": row.get("recipe_id"),
                    "recipe_name": row.get("recipe_name"),
                    "source": row.get("source"),
                    "source_path": row.get("source") or "",
                    "doc_type": "graph_context",
                },
            )
            for row in retrieval_result.graph_evidence
            if row.get("recipe_id")
        ]

        return HybridRetrievalResult(
            query=query,
            filters=filters,
            candidates=candidates,
            graph_evidence=retrieval_result.graph_evidence,
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
        self.retrieval_service.close()

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
