from typing import Callable
from langchain.agents import AgentState
from langchain.agents.middleware import wrap_tool_call, before_model
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from utils.logger_handler import logger


def log_tool_start(tool_name: str, args: dict) -> None:
    """记录工具开始执行及其参数。"""
    logger.info(f"[tool monitor]执行工具：{tool_name}")
    logger.info(f"[tool monitor]传入参数：{args}")


def log_tool_success(tool_name: str) -> None:
    """记录工具执行成功。"""
    logger.info(f"[tool monitor]工具{tool_name}调用成功")


def log_tool_failure(tool_name: str, error: Exception) -> None:
    """记录工具执行失败。"""
    logger.error(f"工具{tool_name}调用失败，原因：{error}")


def log_model_before(messages: list) -> None:
    """记录模型调用前的消息概况。"""
    logger.info(f"[log_before_model]即将调用模型，带有{len(messages)}条消息。")
    if messages:
        last_message = messages[-1]
        content = getattr(last_message, "content", "")
        if isinstance(content, str):
            logger.debug(
                f"[log_before_model]{type(last_message).__name__} | {content.strip()}"
            )


@wrap_tool_call
def monitor_tool(
        # 请求的数据封装
        request: ToolCallRequest,
        # 执行的函数本身
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:             # 工具执行的监控
    tool_name = request.tool_call["name"]
    log_tool_start(tool_name, request.tool_call["args"])

    try:
        result = handler(request)
        log_tool_success(tool_name)

        return result
    except Exception as e:
        log_tool_failure(tool_name, e)
        raise e


@before_model
def log_before_model(
        state: AgentState,          # 整个Agent智能体中的状态记录
        runtime: Runtime,           # 记录了整个执行过程中的上下文信息
):         # 在模型执行前输出日志
    log_model_before(state["messages"])

    return None
