"""Bounded deterministic conversation context for routing and retrieval."""

from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from recipe_assistant.agents.result import MemoryMessage
from recipe_assistant.models import MessageRole


class ConversationResolution(BaseModel):
    """Structured semantic resolution returned by a context agent."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    is_follow_up: bool
    resolved_intent: str = Field(default="", max_length=64)
    referenced_recipe_names: list[str] = Field(default_factory=list, max_length=5)
    rewritten_query: str = Field(default="", max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)


class ConversationContextResolver(Protocol):
    def resolve(
        self,
        history: list[MemoryMessage],
        current_input: str,
        deterministic_context: dict[str, Any],
    ) -> dict[str, Any]: ...


_CONTEXT_REFERENCE = re.compile(
    r"(?:^|[，。？！、\s])(?:那|这个|这些|它|它们|刚才|之前|上面)"
    r"|替换|换成|代替|你不是|你怎么|怎么不清楚|继续|就这样|可以[，,]?\s*那"
)
_IMPLICIT_RECIPE_FOLLOW_UP = re.compile(
    r"^(?:请)?(?:给我|告诉我|介绍一下)?"
    r"(?:详细做法|具体做法|详细步骤|具体步骤|做法|步骤|"
    r"怎么做|需要什么(?:食材|材料)|要多久|需要多久|继续)(?:呢|吧|吗|[？?。！!])?$"
)
_RECIPE_NAME_PATTERNS = (
    re.compile(r"\*\*([^*\n]{2,20})\*\*"),
    re.compile(
        r"(?:推荐(?:您|你)?(?:试试|选择|做|吃)?|"
        r"提供|介绍)(?:一道)?[“\"']?([\u4e00-\u9fff]{2,12}?)"
        r"(?:[”\"']|的|[，。？！、\s]|$)"
    ),
)
_ORDINAL_REFERENCE = re.compile(
    r"第(?P<ordinal>[一二三四五六七八九十\d]+)(?:道|个|份)?(?:菜|食谱)?"
    r"|(?P<last>最后)(?:一道|一个|一份)?(?:菜|食谱)?"
)
_DETAIL_REQUEST = re.compile(r"怎么做|做法|步骤|食材|材料|要多久|需要多久")
_NON_RECIPE_BOLD_TEXT = re.compile(
    r"^\s*(?:\d+[.、．]\s*)?"
    r"(?:准备食材|处理|制作|完成|步骤|操作步骤|必备原料|参考来源|提示|用量)"
)
_CHINESE_ORDINALS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(?:sk|key)-[A-Za-z0-9_-]{8,}"),
)


def _redact(text: str) -> str:
    value = " ".join((text or "").split())
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _latest_recipe_names(messages: list[dict[str, str]]) -> list[str]:
    for message in reversed(messages):
        if message["role"] != MessageRole.ASSISTANT.value:
            continue
        names: list[str] = []
        for pattern in _RECIPE_NAME_PATTERNS:
            for match in pattern.findall(message["content"]):
                name = str(match).strip("“”\"' ，。？！、")
                if 2 <= len(name) <= 20 and name not in names:
                    names.append(name)
        if names:
            return names[:3]
    return []


def has_ordinal_reference(text: str) -> bool:
    return bool(_ORDINAL_REFERENCE.search(text or ""))


def _ordinal_index(text: str) -> int | None:
    match = _ORDINAL_REFERENCE.search(text or "")
    if match is None:
        return None
    if match.group("last"):
        return -1
    value = str(match.group("ordinal") or "")
    number = int(value) if value.isdigit() else _CHINESE_ORDINALS.get(value)
    return number - 1 if number and number > 0 else None


def _ordered_recommendation_names(
    messages: list[dict[str, str]],
) -> list[str]:
    for message in reversed(messages):
        if message["role"] != MessageRole.ASSISTANT.value:
            continue
        content = message["content"]
        if "推荐" not in content and "另外" not in content:
            continue
        names = [
            name.strip("“”\"' ，。？！、")
            for name in re.findall(r"\*\*([^*\n]{2,20})\*\*", content)
        ]
        names = [
            name
            for name in names
            if name and not _NON_RECIPE_BOLD_TEXT.search(name)
        ]
        names = list(dict.fromkeys(names))
        if names:
            return names[:10]
    return []


def build_conversation_context(
    history: list[MemoryMessage],
    current_input: str,
    *,
    max_messages: int = 8,
    max_message_chars: int = 500,
    max_prompt_chars: int = 2400,
) -> dict[str, Any]:
    """Build a safe snapshot and deterministic follow-up query expansion."""

    allowed = {
        MessageRole.USER,
        MessageRole.ASSISTANT,
    }
    messages: list[dict[str, str]] = []
    remaining = max_prompt_chars
    for message in reversed(history):
        if message.role not in allowed or remaining <= 0:
            continue
        content = _clip(_redact(message.content), max_message_chars)
        if not content:
            continue
        content = _clip(content, remaining)
        messages.append(
            {
                "role": message.role.value,
                "content": content,
            }
        )
        remaining -= len(content)
        if len(messages) >= max_messages:
            break
    messages.reverse()

    normalized_input = _redact(current_input)
    implicit_follow_up = bool(_IMPLICIT_RECIPE_FOLLOW_UP.fullmatch(normalized_input))
    recommended_recipe_names = _ordered_recommendation_names(messages)
    ordinal_index = _ordinal_index(normalized_input)
    ordinal_recipe_names: list[str] = []
    if ordinal_index is not None and recommended_recipe_names:
        try:
            ordinal_recipe_names = [recommended_recipe_names[ordinal_index]]
        except IndexError:
            ordinal_recipe_names = []
    resolved_recipe_names = ordinal_recipe_names or (
        _latest_recipe_names(messages) if implicit_follow_up else []
    )
    unresolved_ordinal = (
        has_ordinal_reference(normalized_input) and not ordinal_recipe_names
    )
    context_applied = bool(messages) and bool(
        (
            _CONTEXT_REFERENCE.search(normalized_input)
            and not unresolved_ordinal
        )
        or (implicit_follow_up and resolved_recipe_names)
        or ordinal_recipe_names
    )
    if not context_applied:
        return {
            "messages": messages,
            "routing_query": normalized_input,
            "retrieval_query": normalized_input,
            "context_applied": False,
            "resolved_recipe_names": [],
            "recommended_recipe_names": recommended_recipe_names,
            "resolved_intent": "",
            "resolution_source": "none",
            "resolution_confidence": 0.0,
            "resolution_reason": "",
            "llm_trace": {},
        }

    recent_user_inputs = [
        message["content"]
        for message in messages
        if message["role"] == MessageRole.USER.value
    ][-2:]
    routing_suffix = "；".join(_clip(item, 120) for item in recent_user_inputs)
    routing_query = (
        f"{normalized_input}\n此前用户话题：{routing_suffix}"
        if routing_suffix
        else normalized_input
    )
    if resolved_recipe_names:
        resolved_name = resolved_recipe_names[0]
        routing_query = (
            f"{resolved_name}怎么做？"
            if _DETAIL_REQUEST.search(normalized_input)
            else f"{resolved_name} {normalized_input}"
        )

    recent_dialogue = messages[-4:]
    dialogue = "\n".join(
        f"{item['role']}: {_clip(item['content'], 240)}"
        for item in recent_dialogue
    )
    retrieval_query = _clip(
        f"{normalized_input}\n对话上下文：\n{dialogue}",
        1200,
    )
    if resolved_recipe_names:
        retrieval_query = routing_query
    return {
        "messages": messages,
        "routing_query": routing_query,
        "retrieval_query": retrieval_query,
        "context_applied": True,
        "resolved_recipe_names": resolved_recipe_names,
        "recommended_recipe_names": recommended_recipe_names,
        "resolved_intent": (
            "RECIPE_DETAIL"
            if implicit_follow_up
            or (
                ordinal_recipe_names
                and _DETAIL_REQUEST.search(normalized_input)
            )
            else "FOLLOW_UP"
        ),
        "resolution_source": "rule",
        "resolution_confidence": 1.0,
        "resolution_reason": "deterministic follow-up rule matched",
        "llm_trace": {},
    }
