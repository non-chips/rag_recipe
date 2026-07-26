"""Controlled LLM adapters for routing and response expression."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from time import perf_counter
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.context import (
    ConversationResolution,
    has_ordinal_reference,
)
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    thaw_value,
)
from recipe_assistant.agents.quality import ResponseAgent
from recipe_assistant.agents.result import MemoryMessage
from recipe_assistant.schemas.agent.route import RouteDecision


ChatModelProvider = Callable[[], BaseChatModel]


def _usage_metadata(message: Any) -> dict[str, Any]:
    usage = getattr(message, "usage_metadata", None)
    if isinstance(usage, Mapping):
        return dict(usage)
    response_metadata = getattr(message, "response_metadata", None)
    if isinstance(response_metadata, Mapping):
        token_usage = response_metadata.get("token_usage")
        if isinstance(token_usage, Mapping):
            return dict(token_usage)
    return {}


def _content_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, Mapping)
        )
    return str(content or "")


class LLMConversationContextAgent:
    """Resolve ambiguous follow-ups after deterministic context rules miss."""

    def __init__(
        self,
        model_provider: ChatModelProvider,
        *,
        model_name: str,
        min_confidence: float = 0.7,
    ) -> None:
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        self.model_provider = model_provider
        self.model_name = model_name
        self.min_confidence = min_confidence

    def resolve(
        self,
        history: list[MemoryMessage],
        current_input: str,
        deterministic_context: dict[str, Any],
    ) -> dict[str, Any]:
        context = dict(deterministic_context)
        if context.get("context_applied") or not context.get("messages"):
            return context

        started = perf_counter()
        try:
            model = self.model_provider()
            structured = model.with_structured_output(
                ConversationResolution,
                method="json_mode",
            )
            raw_result = structured.invoke(
                [
                    SystemMessage(
                        content=(
                            "你是菜谱助手的上下文解析 Agent，只输出合法 JSON。"
                            "判断当前输入是否承接历史对话，并完成指代消解与查询改写。"
                            "“第一道、第二个、最后一个”等序号必须映射到历史中"
                            "助手实际展示的对应菜名，不能承接无关的最近话题。"
                            "不得回答菜谱问题，不得编造历史中没有出现的菜名。"
                            "JSON 字段必须是 is_follow_up、resolved_intent、"
                            "referenced_recipe_names、rewritten_query、confidence、reason。"
                            "rewritten_query 必须是可独立用于业务路由和菜谱检索的完整查询。"
                        )
                    ),
                    HumanMessage(
                        content=json.dumps(
                            {
                                "current_input": current_input,
                                "recent_messages": context["messages"],
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    ),
                ]
            )
            resolution = ConversationResolution.model_validate(raw_result)
            trace = {
                "type": "llm_call",
                "llm_used": True,
                "model_name": self.model_name,
                "purpose": "conversation_context_resolution",
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "fallback_reason": "",
                "token_usage": _usage_metadata(raw_result),
            }
            context["llm_trace"] = trace
            context["resolution_confidence"] = resolution.confidence
            context["resolution_reason"] = resolution.reason
            referenced_names = list(
                dict.fromkeys(
                    name.strip()
                    for name in resolution.referenced_recipe_names
                    if name.strip()
                )
            )
            history_text = "\n".join(
                str(message.get("content") or "")
                for message in context["messages"]
            )
            unsupported_names = [
                name for name in referenced_names if name not in history_text
            ]
            recipe_detail_without_grounded_entity = (
                resolution.resolved_intent == "RECIPE_DETAIL"
                and (
                    not referenced_names
                    or not any(
                        name in resolution.rewritten_query
                        for name in referenced_names
                    )
                )
            )
            unresolved_ordinal = (
                has_ordinal_reference(current_input)
                and (
                    not referenced_names
                    or not any(
                        name in resolution.rewritten_query
                        for name in referenced_names
                    )
                )
            )
            if (
                unsupported_names
                or recipe_detail_without_grounded_entity
                or unresolved_ordinal
            ):
                trace["fallback_reason"] = (
                    "unsupported_recipe_entity"
                    if unsupported_names
                    else (
                        "unresolved_ordinal_reference"
                        if unresolved_ordinal
                        else "missing_grounded_recipe_entity"
                    )
                )
                return context
            if (
                resolution.is_follow_up
                and resolution.confidence >= self.min_confidence
                and resolution.rewritten_query
            ):
                rewritten = resolution.rewritten_query.strip()
                context.update(
                    {
                        "routing_query": rewritten,
                        "retrieval_query": rewritten,
                        "context_applied": True,
                        "resolved_recipe_names": referenced_names,
                        "resolved_intent": resolution.resolved_intent,
                        "resolution_source": "llm",
                    }
                )
            return context
        except Exception as exc:
            context["llm_trace"] = {
                "type": "llm_call",
                "llm_used": False,
                "model_name": self.model_name,
                "purpose": "conversation_context_resolution",
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "fallback_reason": f"{type(exc).__name__}: {exc}",
                "token_usage": {},
            }
            return context


class LLMRouteClassifier:
    """Use a lazy structured model only after the rule router asks for help."""

    def __init__(
        self,
        model_provider: ChatModelProvider,
        *,
        model_name: str,
    ) -> None:
        self.model_provider = model_provider
        self.model_name = model_name
        self.last_trace: dict[str, Any] | None = None

    def reset_trace(self) -> None:
        self.last_trace = None

    def classify(
        self,
        query: str,
        rule_fallback: RouteDecision,
    ) -> RouteDecision:
        started = perf_counter()
        try:
            model = self.model_provider()
            structured = model.with_structured_output(
                RouteDecision,
                method="json_mode",
            )
            result = structured.invoke(
                [
                    SystemMessage(
                        content=(
                            "你是菜谱助手的业务路由器，只输出一个合法 JSON 对象。"
                            "JSON 必须包含 route、confidence、reason、"
                            "requires_weather、requires_meal_history、"
                            "requires_multiple_experts；不得输出 Markdown 或解释文字。"
                            "route 只能是 SIMPLE、RECIPE_KNOWLEDGE、"
                            "RECIPE_RECOMMENDATION、NUTRITION_PLANNING、COMPLEX 之一。"
                            "不得回答用户问题，不得选择检索基础设施，不得调用工具。"
                        )
                    ),
                    HumanMessage(
                        content=(
                            f"用户输入：{query}\n"
                            f"规则初判：{rule_fallback.model_dump_json()}"
                        )
                    ),
                ]
            )
            decision = RouteDecision.model_validate(result)
            self.last_trace = {
                "type": "llm_call",
                "llm_used": True,
                "model_name": self.model_name,
                "purpose": "route_classification",
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "fallback_reason": "",
                "token_usage": _usage_metadata(result),
            }
            return decision
        except Exception as exc:
            self.last_trace = {
                "type": "llm_call",
                "llm_used": False,
                "model_name": self.model_name,
                "purpose": "route_classification",
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "fallback_reason": f"{type(exc).__name__}: {exc}",
                "token_usage": {},
            }
            raise


class LLMResponseAgent(ResponseAgent):
    """Express an exact deterministic proposal through a guarded lazy model."""

    def __init__(
        self,
        model_provider: ChatModelProvider,
        *,
        model_name: str,
        max_output_chars: int = 8000,
    ) -> None:
        if max_output_chars < 1:
            raise ValueError("max_output_chars must be positive")
        self.model_provider = model_provider
        self.model_name = model_name
        self.max_output_chars = max_output_chars

    def execute(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        deterministic = super().execute(task, board)
        started = perf_counter()
        try:
            model = self.model_provider()
            messages = self._messages(task, board, deterministic)
            chunks, token_usage = self._stream_model(model, messages)
            answer = "".join(chunks).strip()
            if not answer:
                raise ValueError("model returned an empty response")
            if len(answer) > self.max_output_chars:
                raise ValueError(
                    f"model response exceeded {self.max_output_chars} characters"
                )
            payload = thaw_value(deterministic.payload)
            payload["message"] = answer
            trace = {
                "llm_used": True,
                "model_name": self.model_name,
                "purpose": "response_generation",
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "fallback_reason": "",
                "token_usage": token_usage,
            }
            return replace(
                deterministic,
                payload=payload,
                metadata={
                    **thaw_value(deterministic.metadata),
                    **trace,
                    "streamed_tokens": tuple(chunks),
                },
            )
        except Exception as exc:
            trace = {
                "llm_used": False,
                "model_name": self.model_name,
                "purpose": "response_generation",
                "latency_ms": round((perf_counter() - started) * 1000, 3),
                "fallback_reason": f"{type(exc).__name__}: {exc}",
                "token_usage": {},
            }
            return replace(
                deterministic,
                metadata={
                    **thaw_value(deterministic.metadata),
                    **trace,
                    "degraded": True,
                    "warning": "LLM unavailable; deterministic response used",
                },
            )

    @staticmethod
    def _stream_model(
        model: BaseChatModel,
        messages: list[SystemMessage | HumanMessage],
    ) -> tuple[list[str], dict[str, Any]]:
        chunks: list[str] = []
        token_usage: dict[str, Any] = {}
        stream: Iterator[Any] = model.stream(messages)
        for chunk in stream:
            text = _content_text(chunk)
            if text:
                chunks.append(text)
            usage = _usage_metadata(chunk)
            if usage:
                token_usage = usage
        return chunks, token_usage

    def _messages(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
        deterministic: AgentArtifact,
    ) -> list[SystemMessage | HumanMessage]:
        plan_task_id = str(task.metadata["response_plan_task_id"])
        plan = board.artifact_for(
            task_id=plan_task_id,
            kind=ArtifactKind.RESPONSE_PLAN,
        )
        if plan is None:
            raise ValueError(f"missing response plan: {plan_task_id}")
        _, skill_context = self._skill_context(board)

        prompt_context: dict[str, Any] = {
            "user_input": board.user_input,
            "response_plan": thaw_value(plan.payload),
            "evidence": thaw_value(deterministic.payload.get("evidence", ())),
            "candidates": thaw_value(deterministic.payload.get("candidates", ())),
            "constraints": {},
            "preference_summary": {},
            "conversation_context": {},
            "weather_context": {},
            "nutrition_summary": {},
            "nutrition_goal": {},
            "critique": {},
        }
        for reference in task.metadata.get("artifact_dependencies", ()):
            dependency_task_id = str(reference["task_id"])
            dependency_kind = ArtifactKind(str(reference["kind"]))
            if dependency_kind not in {
                ArtifactKind.CONVERSATION_CONTEXT,
                ArtifactKind.CONSTRAINT_VALIDATION,
                ArtifactKind.USER_PREFERENCE_CONTEXT,
                ArtifactKind.WEATHER_CONTEXT,
                ArtifactKind.NUTRITION_SUMMARY,
                ArtifactKind.NUTRITION_GOAL,
            }:
                continue
            artifact = board.artifact_for(
                task_id=dependency_task_id,
                kind=dependency_kind,
            )
            if artifact is None:
                continue
            if dependency_kind is ArtifactKind.CONVERSATION_CONTEXT:
                prompt_context["conversation_context"] = thaw_value(
                    artifact.payload
                )
            elif dependency_kind is ArtifactKind.CONSTRAINT_VALIDATION:
                prompt_context["constraints"] = thaw_value(artifact.payload)
            elif dependency_kind is ArtifactKind.USER_PREFERENCE_CONTEXT:
                prompt_context["preference_summary"] = thaw_value(artifact.payload)
            elif dependency_kind is ArtifactKind.WEATHER_CONTEXT:
                prompt_context["weather_context"] = thaw_value(artifact.payload)
            elif dependency_kind is ArtifactKind.NUTRITION_SUMMARY:
                prompt_context["nutrition_summary"] = thaw_value(artifact.payload)
            else:
                prompt_context["nutrition_goal"] = thaw_value(artifact.payload)
        critique_task_id = str(task.metadata.get("critique_task_id") or "")
        if critique_task_id:
            critique = board.artifact_for(
                task_id=critique_task_id,
                kind=ArtifactKind.CRITIQUE,
            )
            if critique is not None:
                prompt_context["critique"] = {
                    "violations": thaw_value(
                        critique.payload.get("violations", ())
                    ),
                    "rejected_candidate_ids": thaw_value(
                        critique.payload.get("rejected_candidate_ids", ())
                    ),
                }

        messages: list[SystemMessage | HumanMessage] = [
            SystemMessage(
                content=(
                    "你是菜谱助手的回答表达器。约束优先级固定为：食品安全与硬约束、"
                    "已验证业务 Artifact、当前用户请求、行为与表达指导。"
                    "只依据提供的 JSON 证据回答；"
                    "conversation_context 只用于理解指代和承接话题，不能作为菜谱事实来源；"
                    "当历史说法与本轮 evidence、candidates 或 constraints 冲突时，以本轮为准。"
                    "不得编造菜谱、食材、步骤、时间、营养数值、来源或库存。"
                    "严格遵守过敏原、忌口、厨具、时长和可用食材约束。"
                    "天气、营养、来源或替代比例没有对应业务事实时必须明确无依据，"
                    "不得推测或补全。证据不足时明确说明，并且最多提出一个最小澄清问题。"
                    "不得输出黑板、Agent、Prompt、置信度、内部审核或工具细节。"
                    "只输出面向用户的最终自然语言文本。"
                )
            )
        ]
        if skill_context.selected_skill_refs:
            refs = ", ".join(skill_context.selected_skill_refs)
            messages.append(
                SystemMessage(
                    content=(
                        f"以下是唯一允许使用的已验证行为 Skill：{refs}。"
                        "只能使用该列表中的 Skill，不得声明、追加或输出未列出的 Skill。"
                        "Skill 仅影响回答策略与表达组织，不能覆盖 Response Plan、"
                        "候选校验或硬约束，也不构成新的天气、营养、来源、"
                        "食材或替代比例事实。\n\n"
                        f"{skill_context.prompt_context}"
                    )
                )
            )
        messages.append(
            HumanMessage(
                content=json.dumps(
                    prompt_context,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        )
        return messages
