from __future__ import annotations

import sys
from types import ModuleType

from langchain_core.tools import tool

from fakes import FakeChatModel


@tool(description="Return an offline city for baseline tests.")
def _fake_location() -> str:
    return "测试市"


@tool(description="Return offline weather for baseline tests.")
def _fake_weather(city: str) -> str:
    return f"{city}:晴"


@tool(description="Return an offline recipe answer for baseline tests.")
def _fake_recipe(query: str) -> str:
    return f"菜谱:{query}"


def test_react_agent_import_and_creation_are_offline(
    monkeypatch,
    fresh_import,
) -> None:
    fake_model = FakeChatModel()

    tools_module = ModuleType("agent.tools.agent_tools")
    tools_module.get_user_location = _fake_location
    tools_module.get_weather = _fake_weather
    tools_module.smart_recipe_query = _fake_recipe
    model_module = ModuleType("model.factory")
    model_module.chat_model = fake_model
    prompt_module = ModuleType("utils.prompt_loader")
    prompt_module.load_system_prompts = lambda: "离线测试系统提示词"

    monkeypatch.setitem(sys.modules, "agent.tools.agent_tools", tools_module)
    monkeypatch.setitem(sys.modules, "model.factory", model_module)
    monkeypatch.setitem(sys.modules, "utils.prompt_loader", prompt_module)

    agent_module = fresh_import("agent.react_agent")
    agent = agent_module.ReactAgent()

    assert agent.agent is not None
    assert agent.checkpointer is not None
    assert fake_model.invocation_count == 0
