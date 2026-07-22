# LLM 自主工具调用的菜谱问答 Agent

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from agent.tools.agent_tools import (
    get_user_location,
    get_weather,
    smart_recipe_query,
)
from agent.tools.middleware import log_before_model, monitor_tool
from model.factory import chat_model
from utils.prompt_loader import load_system_prompts


class ReactAgent:
    def __init__(self):
        self.checkpointer = InMemorySaver()
        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompts(),
            tools=[
                get_user_location,
                get_weather,
                smart_recipe_query,
            ],
            middleware=[
                monitor_tool,
                log_before_model,
            ],
            checkpointer=self.checkpointer,
        )

    def execute_stream(
        self,
        query: str,
        thread_id: str,
    ):
        input_dict = {
            "messages": [
                {
                    "role": "user",
                    "content": query,
                }
            ]
        }
        config = {
            "configurable": {
                "thread_id": thread_id,
            }
        }

        reasoning_started = False
        answer_started = False
        in_thinking_tag = False

        for message, _metadata in self.agent.stream(
            input_dict,
            config=config,
            stream_mode="messages",
        ):
            if not isinstance(message, AIMessageChunk):
                continue

            reasoning_parts, answer_parts, in_thinking_tag = (
                self._extract_chunk_parts(
                    message,
                    in_thinking_tag=in_thinking_tag,
                )
            )

            if reasoning_parts:
                if not reasoning_started:
                    reasoning_started = True
                    yield "【思考过程】\n"
                yield "".join(reasoning_parts)

            if answer_parts:
                if not answer_started:
                    answer_started = True
                    yield "\n\n【思考过程】\n"
                yield "".join(answer_parts)

    @staticmethod
    def _extract_chunk_parts(
        message: AIMessageChunk,
        in_thinking_tag: bool = False,
    ) -> tuple[list[str], list[str], bool]:
        """兼容 DeepSeek/OpenAI 兼容接口的思考内容和回答内容。"""
        reasoning_parts: list[str] = []
        answer_parts: list[str] = []

        additional_kwargs = getattr(message, "additional_kwargs", {}) or {}
        reasoning_content = (
            additional_kwargs.get("reasoning_content")
            or additional_kwargs.get("reasoning")
        )
        if isinstance(reasoning_content, str) and reasoning_content:
            reasoning_parts.append(reasoning_content)

        content = message.content
        if isinstance(content, str):
            reasoning, answer, in_thinking_tag = ReactAgent._split_thinking_tags(
                content,
                in_thinking_tag,
            )
            reasoning_parts.extend(reasoning)
            answer_parts.extend(answer)
            return reasoning_parts, answer_parts, in_thinking_tag

        if not isinstance(content, list):
            return reasoning_parts, answer_parts, in_thinking_tag

        for block in content:
            if not isinstance(block, dict):
                continue

            block_type = str(block.get("type", "")).lower()
            block_reasoning = (
                block.get("reasoning")
                or block.get("reasoning_content")
                or block.get("thinking")
            )
            if block_type in {"reasoning", "thinking"} or block_reasoning:
                text = block_reasoning or block.get("text") or block.get("content")
                if isinstance(text, str) and text:
                    reasoning_parts.append(text)
                continue

            text = block.get("text") or block.get("content")
            if isinstance(text, str) and text:
                reasoning, answer, in_thinking_tag = ReactAgent._split_thinking_tags(
                    text,
                    in_thinking_tag,
                )
                reasoning_parts.extend(reasoning)
                answer_parts.extend(answer)

        return reasoning_parts, answer_parts, in_thinking_tag

    @staticmethod
    def _split_thinking_tags(
        text: str,
        in_thinking_tag: bool,
    ) -> tuple[list[str], list[str], bool]:
        """把嵌在普通文本中的 <think> 内容拆分为思考和回答。"""
        reasoning_parts: list[str] = []
        answer_parts: list[str] = []
        remaining = text

        while remaining:
            if in_thinking_tag:
                end_index = remaining.find("</think>")
                if end_index < 0:
                    reasoning_parts.append(remaining)
                    return reasoning_parts, answer_parts, True

                if end_index:
                    reasoning_parts.append(remaining[:end_index])
                remaining = remaining[end_index + len("</think>"):]
                in_thinking_tag = False
                continue

            start_index = remaining.find("<think>")
            if start_index < 0:
                answer_parts.append(remaining)
                return reasoning_parts, answer_parts, False

            if start_index:
                answer_parts.append(remaining[:start_index])
            remaining = remaining[start_index + len("<think>"):]
            in_thinking_tag = True

        return reasoning_parts, answer_parts, in_thinking_tag


if __name__ == "__main__":
    agent = ReactAgent()

    for chunk in agent.execute_stream(
        query="根据今天的天气推荐一道菜",
        thread_id="test_thread",
    ):
        print(chunk, end="", flush=True)
