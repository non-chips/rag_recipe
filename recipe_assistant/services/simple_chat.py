"""Deterministic fast path for greetings and capability questions."""

from __future__ import annotations

from recipe_assistant.schemas.agent.route import (
    SimpleChatCategory,
    SimpleChatResponse,
)


class SimpleChatService:
    """Answer simple chat without invoking retrieval or an expert runtime."""

    def respond(self, message: str) -> SimpleChatResponse:
        text = (message or "").strip()
        lowered = text.lower()
        if not text:
            return SimpleChatResponse(
                category=SimpleChatCategory.EMPTY,
                message="你好，可以告诉我你想了解的菜谱、推荐条件或营养问题。",
            )
        if any(term in lowered for term in ("谢谢", "感谢", "thank")):
            return SimpleChatResponse(
                category=SimpleChatCategory.THANKS,
                message="不客气，很高兴能帮到你。",
            )
        if any(term in lowered for term in ("你能做什么", "你是谁", "功能")):
            return SimpleChatResponse(
                category=SimpleChatCategory.CAPABILITY,
                message="我可以查询菜谱做法、按条件推荐菜谱，并协助分析饮食与营养。",
            )
        if any(term in lowered for term in ("再见", "拜拜", "bye")):
            return SimpleChatResponse(
                category=SimpleChatCategory.FAREWELL,
                message="再见，想做饭时随时来找我。",
            )
        if any(term in lowered for term in ("你好", "您好", "嗨", "hello", "hi")):
            return SimpleChatResponse(
                category=SimpleChatCategory.GREETING,
                message="你好，我是你的食谱助手。今天想做点什么？",
            )
        return SimpleChatResponse(
            category=SimpleChatCategory.GENERAL,
            message="我在这里，可以继续告诉我你的菜谱或营养需求。",
        )
