from __future__ import annotations

from sqlalchemy import func, select

from recipe_assistant.agents.harness import RecipeAgentHarness
from recipe_assistant.agents.result import ChatRequest, RunStatus
from recipe_assistant.agents.router import BusinessRouter
from recipe_assistant.core.database import (
    Base,
    create_database_engine,
    create_session_factory,
    session_scope,
)
from recipe_assistant.models import AgentRunTrace, ChatMessage, MessageRole
from recipe_assistant.repositories import (
    SqlAlchemyProfileRepository,
    SqlAlchemyTraceRepository,
    SqlAlchemyUserRepository,
)
from recipe_assistant.services.chat import ChatService
from recipe_assistant.services.simple_chat import SimpleChatService


class _Executor:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    def execute(self, query: str, thread_id: str) -> str:
        self.calls.append((query, thread_id))
        if self.fail:
            raise RuntimeError("executor failed")
        return f"最终回答：{query}"


def _build_service(*, fail: bool = False):
    engine = create_database_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    executor = _Executor(fail=fail)
    harness = RecipeAgentHarness(BusinessRouter(), SimpleChatService(), executor)
    return engine, factory, executor, ChatService(factory, harness)


def test_chat_service_creates_and_restores_session_with_profile_history_and_trace() -> None:
    engine, factory, executor, service = _build_service()
    with session_scope(factory) as session:
        user = SqlAlchemyUserRepository(session).create("chat-user", "hash")
        SqlAlchemyProfileRepository(session).upsert(
            user.id,
            allergens_json=["花生"],
            preferred_cuisines_json=["粤菜"],
        )
        user_id = user.id

    first = service.run(ChatRequest(user_id=user_id, message="你好"))
    assert first.content.startswith("你好")
    assert executor.calls == []
    assert first.outcome.context.history == []

    second = service.run(
        ChatRequest(
            user_id=user_id,
            message="  清蒸鱼   怎么做  ",
            session_public_id=first.session_public_id,
        )
    )
    assert second.session_public_id == first.session_public_id
    assert second.content == "最终回答：清蒸鱼 怎么做"
    assert second.outcome.context.profile.allergens == ["花生"]
    assert second.outcome.context.profile.preferred_cuisines == ["粤菜"]
    assert [message.role for message in second.outcome.context.history] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert len(executor.calls) == 1

    with session_scope(factory) as session:
        messages = list(session.scalars(select(ChatMessage).order_by(ChatMessage.id)))
        traces = list(session.scalars(select(AgentRunTrace).order_by(AgentRunTrace.id)))
        assert [message.role for message in messages] == [
            MessageRole.USER,
            MessageRole.ASSISTANT,
            MessageRole.USER,
            MessageRole.ASSISTANT,
        ]
        assert len(traces) == 2
        assert SqlAlchemyTraceRepository(session).get_by_run_id(second.run_id) is not None
        assert traces[-1].route == "RECIPE_KNOWLEDGE"

    engine.dispose()


def test_failed_executor_still_saves_final_message_and_trace() -> None:
    engine, factory, _executor, service = _build_service(fail=True)
    with session_scope(factory) as session:
        user_id = SqlAlchemyUserRepository(session).create("failed-user", "hash").id

    result = service.run(ChatRequest(user_id=user_id, message="红烧肉怎么做"))

    assert result.outcome.result.status is RunStatus.FAILED
    assert result.content == "抱歉，本次请求暂时无法完成，请稍后重试。"
    with session_scope(factory) as session:
        assert session.scalar(select(func.count()).select_from(ChatMessage)) == 2
        trace = session.scalar(select(AgentRunTrace))
        assert trace is not None
        assert trace.events_json[-1]["type"] == "execution_error"

    engine.dispose()
