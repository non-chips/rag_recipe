"""Replaceable Streamlit client using only the public HTTP/SSE contract."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from uuid import uuid4

import requests
import streamlit as st


API_BASE_URL = os.getenv("FRONTEND_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
USER_ID = int(os.getenv("FRONTEND_USER_ID", "1"))


def stream_chat(message: str, session_id: str | None) -> Iterator[str]:
    response = requests.post(
        f"{API_BASE_URL}/api/chat/stream",
        headers={"X-User-Id": str(USER_ID), "Accept": "text/event-stream"},
        json={"message": message, "sessionId": session_id},
        stream=True,
        timeout=(5, 180),
    )
    response.raise_for_status()
    event_name = ""
    for raw_line in response.iter_lines(decode_unicode=True):
        line = raw_line.strip()
        if not line:
            event_name = ""
            continue
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
            continue
        if not line.startswith("data:"):
            continue
        event = json.loads(line.removeprefix("data:").strip())
        event_type = event.get("type") or event_name
        if event_type == "meta":
            st.session_state["session_id"] = event["sessionId"]
            st.session_state["run_id"] = event["runId"]
        elif event_type == "token":
            yield str(event.get("content", ""))
        elif event_type == "error":
            yield f"\n\n请求失败：{event.get('message', '未知错误')}"


st.set_page_config(page_title="智能菜谱推荐助手", page_icon="🍲")
st.title("智能菜谱推荐助手")
st.caption(f"API: {API_BASE_URL}")

if "client_id" not in st.session_state:
    st.session_state["client_id"] = uuid4().hex
if "session_id" not in st.session_state:
    st.session_state["session_id"] = None
if "messages" not in st.session_state:
    st.session_state["messages"] = []

for item in st.session_state["messages"]:
    with st.chat_message(item["role"]):
        st.write(item["content"])

prompt = st.chat_input("请输入菜谱问题，或让我根据天气推荐菜谱")
if prompt:
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"):
        try:
            answer = st.write_stream(
                stream_chat(prompt, st.session_state.get("session_id"))
            )
        except requests.RequestException as exc:
            answer = f"无法连接后端 API：{exc}"
            st.error(answer)
    st.session_state["messages"].append(
        {"role": "assistant", "content": str(answer)}
    )

