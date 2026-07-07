#创建 LangChain Agent

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.memory import InMemorySaver

from model.factory import chat_model
from utils.prompt_loader import load_system_prompts
from agent.tools.agent_tools import (
    rag_summarize,
    route_recipe_query,
    hybrid_rag_summarize,
    get_weather,
    get_user_location,
    graph_recipe_search,
)
from agent.tools.middleware import (
    monitor_tool,
    log_before_model,
)


class ReactAgent:
    def __init__(self):
        # 保存每个 thread_id 对应的短期对话历史
        self.checkpointer = InMemorySaver()

        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompts(),
            tools=[
                route_recipe_query,
                rag_summarize,
                hybrid_rag_summarize,
                get_weather,
                get_user_location,
                graph_recipe_search,
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

        for message, metadata in self.agent.stream(
            input_dict,
            config=config,
            stream_mode="messages",
        ):
            # 只输出主模型最终生成的文本 token，
            # 跳过工具调用参数和工具内部消息
            if not isinstance(message, AIMessageChunk):
                continue

            content = message.content

            if isinstance(content, str) and content:
                yield content


if __name__ == "__main__":
    agent = ReactAgent()

    for chunk in agent.execute_stream(
        query="根据今天的天气推荐一道菜",
        thread_id="test_thread"
    ):
        print(chunk, end="", flush=True)
