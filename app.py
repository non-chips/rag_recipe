import uuid

import streamlit as st

from agent.react_agent import ReactAgent


st.set_page_config(
    page_title="智能菜谱推荐助手",
    page_icon="🍲",
)

st.title("智能菜谱推荐助手")
st.divider()


# 每个浏览器会话创建一个 Agent
if "agent" not in st.session_state:
    st.session_state["agent"] = ReactAgent()


# 每个聊天会话对应一个稳定的 thread_id
if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = str(uuid.uuid4())


# 这里只用于界面显示，不再承担模型记忆功能
if "messages" not in st.session_state:
    st.session_state["messages"] = []


# 显示历史消息
for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        st.write(message["content"])


prompt = st.chat_input(
    "请输入菜谱问题，或让我根据天气推荐菜谱"
)

if prompt:
    # 显示并保存用户消息
    with st.chat_message("user"):
        st.write(prompt)

    st.session_state["messages"].append(
        {
            "role": "user",
            "content": prompt,
        }
    )

    # 调用同一个 thread_id 下的 Agent
    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            response_stream = (
                st.session_state["agent"].execute_stream(
                    query=prompt,
                    thread_id=st.session_state["thread_id"],
                )
            )

            full_response = st.write_stream(
                response_stream
            )

    # 保存完整助手回答，只用于页面重绘
    st.session_state["messages"].append(
        {
            "role": "assistant",
            "content": full_response,
        }
    )
