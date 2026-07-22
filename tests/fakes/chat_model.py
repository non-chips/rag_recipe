from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeChatModel(BaseChatModel):
    """Deterministic offline chat model that is compatible with LangChain."""

    response_text: str = "离线模型回答"
    invocation_count: int = 0
    bound_tool_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def _generate(
        self,
        messages: list[Any],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        self.invocation_count += 1
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content=self.response_text),
                )
            ]
        )

    def bind_tools(
        self,
        tools: list[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> FakeChatModel:
        del tool_choice, kwargs
        self.bound_tool_count = len(tools)
        return self
