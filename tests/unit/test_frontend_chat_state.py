from __future__ import annotations

import ast
from pathlib import Path

from frontend.chat_state import merge_server_messages


def test_server_history_restores_answer_lost_during_frontend_rerun() -> None:
    local = [
        {"role": "user", "content": "那凉拌豆腐怎么做？"},
    ]
    server = [
        {
            "id": 24,
            "role": "USER",
            "content": "那凉拌豆腐怎么做？",
            "created_at": "2026-07-25T02:42:16Z",
        },
        {
            "id": 25,
            "role": "ASSISTANT",
            "content": "这是凉拌豆腐的做法。",
            "created_at": "2026-07-25T02:42:29Z",
        },
    ]

    merged = merge_server_messages(local, server)

    assert [item["content"] for item in merged] == [
        "那凉拌豆腐怎么做？",
        "这是凉拌豆腐的做法。",
    ]
    assert merged[1]["message_id"] == 25


def test_feedback_handler_does_not_force_a_page_rerun_and_buttons_can_disable() -> None:
    source_path = Path("frontend/streamlit_app.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    render_feedback = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "render_feedback"
    )
    calls = [
        node
        for node in ast.walk(render_feedback)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "st"
    ]

    assert all(call.func.attr != "rerun" for call in calls)
    button_calls = [
        node
        for node in ast.walk(render_feedback)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "button"
    ]
    assert button_calls
    assert all(
        any(keyword.arg == "disabled" for keyword in call.keywords)
        for call in button_calls
    )
