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
REASON_TAGS = {
    "回答不正确": "INCORRECT",
    "与问题无关": "IRRELEVANT",
    "存在安全问题": "UNSAFE",
    "违反了我的约束": "CONSTRAINT_VIOLATION",
    "信息已过时": "OUTDATED",
    "表达不清": "UNCLEAR",
    "过于冗长": "TOO_VERBOSE",
    "过于简略": "TOO_BRIEF",
    "其他": "OTHER",
}


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
            st.session_state["response_run_id"] = event["runId"]
        elif event_type == "token":
            yield str(event.get("content", ""))
        elif event_type == "done":
            st.session_state["response_message_id"] = event["messageId"]
        elif event_type == "error":
            yield f"\n\n请求失败：{event.get('message', '未知错误')}"


def load_feedback(message_id: int) -> dict | None:
    response = requests.get(
        f"{API_BASE_URL}/api/feedback/{message_id}",
        headers={"X-User-Id": str(USER_ID)},
        timeout=10,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def submit_feedback(
    item: dict,
    rating: str,
    reason_tags: list[str] | None = None,
    comment: str | None = None,
) -> dict:
    response = requests.post(
        f"{API_BASE_URL}/api/feedback",
        headers={"X-User-Id": str(USER_ID)},
        json={
            "run_id": item["run_id"],
            "message_id": item["message_id"],
            "rating": rating,
            "reason_tags": reason_tags or [],
            "comment": comment,
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def render_feedback(item: dict) -> None:
    message_id = item.get("message_id")
    if not message_id or not item.get("run_id"):
        return
    if "feedback" not in item:
        try:
            item["feedback"] = load_feedback(message_id)
        except requests.RequestException:
            item["feedback"] = None

    current = item.get("feedback")
    left, right = st.columns(2)
    try:
        if left.button(
            "👍 有帮助",
            key=f"feedback-like-{message_id}",
            type="primary" if current and current["rating"] == "LIKE" else "secondary",
        ):
            item["feedback"] = submit_feedback(item, "LIKE")
            st.rerun()
        if right.button(
            "👎 没帮助",
            key=f"feedback-dislike-{message_id}",
            type=(
                "primary" if current and current["rating"] == "DISLIKE" else "secondary"
            ),
        ):
            item["feedback"] = submit_feedback(item, "DISLIKE")
            st.rerun()
    except requests.RequestException as exc:
        st.error(f"反馈提交失败：{exc}")

    if current:
        label = "有帮助" if current["rating"] == "LIKE" else "没帮助"
        st.caption(f"已记录：{label}")
    with st.expander("补充反馈原因（可选）"):
        default_rating = 0 if not current or current["rating"] == "LIKE" else 1
        with st.form(f"feedback-detail-{message_id}"):
            rating_label = st.radio(
                "评价", ["有帮助", "没帮助"], index=default_rating, horizontal=True
            )
            selected = st.multiselect(
                "原因",
                list(REASON_TAGS),
                default=[
                    label
                    for label, value in REASON_TAGS.items()
                    if current and value in current.get("reason_tags", [])
                ],
            )
            existing_comment = current.get("comment") or "" if current else ""
            comment = st.text_area("评论", value=existing_comment, max_chars=1000)
            save = st.form_submit_button("保存反馈")
        if save:
            try:
                item["feedback"] = submit_feedback(
                    item,
                    "LIKE" if rating_label == "有帮助" else "DISLIKE",
                    [REASON_TAGS[label] for label in selected],
                    comment,
                )
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"反馈提交失败：{exc}")


st.set_page_config(page_title="智能菜谱推荐助手", page_icon="🍅")
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
        if item["role"] == "assistant":
            render_feedback(item)

prompt = st.chat_input("请输入菜谱问题，或让我根据天气推荐菜谱")
if prompt:
    st.session_state.pop("response_run_id", None)
    st.session_state.pop("response_message_id", None)
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
        {
            "role": "assistant",
            "content": str(answer),
            "run_id": st.session_state.get("response_run_id"),
            "message_id": st.session_state.get("response_message_id"),
        }
    )
