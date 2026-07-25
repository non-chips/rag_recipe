from __future__ import annotations

from recipe_assistant.agents.context import build_conversation_context
from recipe_assistant.agents.factory import MultiExpertHarness
from recipe_assistant.agents.llm import LLMConversationContextAgent
from recipe_assistant.agents.result import MemoryMessage, ProfileSnapshot, RunContext
from recipe_assistant.core.database import utc_now
from recipe_assistant.models import MessageRole
from recipe_assistant.schemas.agent.route import RouteDecision, RouteType


def _message(role: MessageRole, content: str) -> MemoryMessage:
    return MemoryMessage(
        role=role,
        content=content,
        created_at=utc_now(),
    )


def test_follow_up_builds_bounded_contextual_queries_and_redacts_secrets() -> None:
    history = [
        _message(MessageRole.USER, "那凉皮怎么做？"),
        _message(
            MessageRole.ASSISTANT,
            "凉皮需要凉皮、面筋、黄瓜和豆芽。Bearer super-secret-token",
        ),
    ]

    context = build_conversation_context(
        history,
        "黄瓜不新鲜了，可以拿什么替换？",
    )

    assert context["context_applied"] is True
    assert "凉皮" in context["routing_query"]
    assert "凉皮" in context["retrieval_query"]
    assert "黄瓜不新鲜" in context["retrieval_query"]
    assert "super-secret-token" not in str(context)
    assert "[REDACTED]" in str(context)


def test_standalone_question_keeps_retrieval_query_unchanged() -> None:
    history = [
        _message(MessageRole.USER, "凉皮怎么做？"),
        _message(MessageRole.ASSISTANT, "这里是凉皮步骤。"),
    ]

    context = build_conversation_context(history, "红烧肉怎么做？")

    assert context["context_applied"] is False
    assert context["routing_query"] == "红烧肉怎么做？"
    assert context["retrieval_query"] == "红烧肉怎么做？"
    assert len(context["messages"]) == 2


def test_implicit_recipe_detail_follow_up_carries_latest_recipe_entity() -> None:
    history = [
        _message(MessageRole.USER, "今天天气真热，推荐吃什么菜？"),
        _message(
            MessageRole.ASSISTANT,
            "推荐口水鸡。需要我提供口水鸡的详细做法吗？",
        ),
    ]

    context = build_conversation_context(history, "详细做法")

    assert context["context_applied"] is True
    assert "口水鸡" in context["routing_query"]
    assert "口水鸡" in context["retrieval_query"]
    assert context["resolved_recipe_names"] == ["口水鸡"]


def test_ordinal_follow_up_resolves_user_visible_recommendation_order() -> None:
    history = [
        _message(MessageRole.USER, "今天天气真热，推荐吃什么菜？"),
        _message(
            MessageRole.ASSISTANT,
            (
                "天气热的时候推荐 **口水鸡**。另外，**凉拌鸡丝**、"
                "**凉拌豆腐**、**凉拌金针菇** 和 **凉皮** 也很清爽。"
            ),
        ),
        _message(MessageRole.USER, "凉拌豆腐怎么做？"),
        _message(
            MessageRole.ASSISTANT,
            "豆腐焯水 1-2 分钟，再加入调味汁。",
        ),
    ]

    context = build_conversation_context(
        history,
        "好，那你推荐的第一道菜怎么做？",
    )

    assert context["resolution_source"] == "rule"
    assert context["resolved_intent"] == "RECIPE_DETAIL"
    assert context["recommended_recipe_names"] == [
        "口水鸡",
        "凉拌鸡丝",
        "凉拌豆腐",
        "凉拌金针菇",
        "凉皮",
    ]
    assert context["resolved_recipe_names"] == ["口水鸡"]
    assert context["routing_query"] == "口水鸡怎么做？"
    assert context["retrieval_query"] == "口水鸡怎么做？"


class _StructuredContextModel:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        from recipe_assistant.agents.context import ConversationResolution

        assert schema is ConversationResolution
        assert kwargs == {"method": "json_mode"}
        return self

    def invoke(self, messages):
        assert len(messages) == 2
        self.calls += 1
        return self.result


def test_llm_context_agent_resolves_ambiguous_follow_up_not_covered_by_rules() -> None:
    from recipe_assistant.agents.context import ConversationResolution

    model = _StructuredContextModel(
        ConversationResolution(
            is_follow_up=True,
            resolved_intent="RECIPE_DETAIL",
            referenced_recipe_names=["凉拌豆腐"],
            rewritten_query="凉拌豆腐的详细做法",
            confidence=0.94,
            reason="“第二个”指向上一轮推荐列表中的第二道菜",
        )
    )
    agent = LLMConversationContextAgent(
        lambda: model,
        model_name="context-fake",
    )
    history = [
        _message(MessageRole.USER, "推荐两道夏天吃的菜"),
        _message(MessageRole.ASSISTANT, "第一道口水鸡，第二道凉拌豆腐。"),
    ]

    context = agent.resolve(
        history,
        "第二个怎么做？",
        build_conversation_context(history, "第二个怎么做？"),
    )

    assert model.calls == 1
    assert context["context_applied"] is True
    assert context["resolution_source"] == "llm"
    assert context["resolved_intent"] == "RECIPE_DETAIL"
    assert context["resolved_recipe_names"] == ["凉拌豆腐"]
    assert context["routing_query"] == "凉拌豆腐的详细做法"
    assert context["retrieval_query"] == "凉拌豆腐的详细做法"
    assert context["resolution_confidence"] == 0.94
    assert context["llm_trace"]["purpose"] == "conversation_context_resolution"


def test_llm_context_agent_failure_preserves_deterministic_fallback() -> None:
    history = [
        _message(MessageRole.USER, "推荐两道菜"),
        _message(MessageRole.ASSISTANT, "第一道口水鸡，第二道凉拌豆腐。"),
    ]
    fallback = build_conversation_context(history, "第二个怎么做？")
    agent = LLMConversationContextAgent(
        lambda: (_ for _ in ()).throw(TimeoutError("context timeout")),
        model_name="offline-context",
    )

    context = agent.resolve(history, "第二个怎么做？", fallback)

    assert context["routing_query"] == fallback["routing_query"]
    assert context["retrieval_query"] == fallback["retrieval_query"]
    assert context["context_applied"] is False
    assert context["resolution_source"] == "none"
    assert context["llm_trace"]["llm_used"] is False
    assert "TimeoutError" in context["llm_trace"]["fallback_reason"]


def test_llm_context_agent_rejects_recipe_entity_absent_from_history() -> None:
    from recipe_assistant.agents.context import ConversationResolution

    model = _StructuredContextModel(
        ConversationResolution(
            is_follow_up=True,
            resolved_intent="RECIPE_DETAIL",
            referenced_recipe_names=["宫保鸡丁"],
            rewritten_query="宫保鸡丁的详细做法",
            confidence=0.98,
            reason="模型错误地补充了历史中不存在的菜名",
        )
    )
    history = [
        _message(MessageRole.USER, "推荐两道菜"),
        _message(MessageRole.ASSISTANT, "第一道口水鸡，第二道凉拌豆腐。"),
    ]
    fallback = build_conversation_context(history, "第二个怎么做？")

    context = LLMConversationContextAgent(
        lambda: model,
        model_name="context-fake",
    ).resolve(history, "第二个怎么做？", fallback)

    assert context["context_applied"] is False
    assert context["resolution_source"] == "none"
    assert context["routing_query"] == "第二个怎么做？"
    assert context["llm_trace"]["llm_used"] is True
    assert "unsupported_recipe_entity" in context["llm_trace"]["fallback_reason"]


def test_llm_context_agent_rejects_unresolved_ordinal_rewrite() -> None:
    from recipe_assistant.agents.context import ConversationResolution

    model = _StructuredContextModel(
        ConversationResolution(
            is_follow_up=True,
            resolved_intent="clarify_misunderstanding",
            referenced_recipe_names=[],
            rewritten_query="用户询问是否设置过制作时长条件",
            confidence=0.95,
            reason="错误地承接了最近一轮话题",
        )
    )
    history = [
        _message(MessageRole.USER, "推荐两道菜"),
        _message(MessageRole.ASSISTANT, "推荐口水鸡和凉拌豆腐。"),
    ]
    fallback = build_conversation_context(
        history,
        "你给我推荐的第一道菜怎么做？",
    )

    context = LLMConversationContextAgent(
        lambda: model,
        model_name="context-fake",
    ).resolve(
        history,
        "你给我推荐的第一道菜怎么做？",
        fallback,
    )

    assert context["context_applied"] is False
    assert context["resolution_source"] == "none"
    assert context["routing_query"] == "你给我推荐的第一道菜怎么做？"
    assert "unresolved_ordinal_reference" in context["llm_trace"]["fallback_reason"]


def test_rule_resolved_context_does_not_call_llm_agent() -> None:
    provider_calls = 0

    def provider():
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("rule fast path must not initialize the model")

    agent = LLMConversationContextAgent(provider, model_name="unused")
    history = [
        _message(MessageRole.USER, "推荐一道菜"),
        _message(MessageRole.ASSISTANT, "推荐口水鸡，需要详细做法吗？"),
    ]
    fallback = build_conversation_context(history, "详细做法")

    context = agent.resolve(history, "详细做法", fallback)

    assert context["context_applied"] is True
    assert context["resolution_source"] == "rule"
    assert provider_calls == 0


def test_harness_applies_llm_rewrite_before_business_routing() -> None:
    from recipe_assistant.agents.context import ConversationResolution

    model = _StructuredContextModel(
        ConversationResolution(
            is_follow_up=True,
            resolved_intent="RECIPE_DETAIL",
            referenced_recipe_names=["凉拌豆腐"],
            rewritten_query="凉拌豆腐的详细做法",
            confidence=0.91,
            reason="承接推荐列表中的第二道菜",
        )
    )

    class _CapturingSimpleRouter:
        classifier = None

        def __init__(self) -> None:
            self.query = ""

        def route(self, query: str) -> RouteDecision:
            self.query = query
            return RouteDecision(
                route=RouteType.SIMPLE,
                confidence=1.0,
                reason="capture context only",
            )

    router = _CapturingSimpleRouter()
    harness = MultiExpertHarness(
        runtime_provider=lambda: (_ for _ in ()).throw(
            AssertionError("simple route must not initialize runtime")
        ),
        router=router,  # type: ignore[arg-type]
        context_resolver=LLMConversationContextAgent(
            lambda: model,
            model_name="context-fake",
        ),
    )
    context = RunContext(
        user_id=1,
        session_id=1,
        session_public_id="context-agent-session",
        original_input="第二个怎么做？",
        normalized_input="第二个怎么做？",
        profile=ProfileSnapshot(),
        history=[
            _message(MessageRole.USER, "推荐两道夏天吃的菜"),
            _message(
                MessageRole.ASSISTANT,
                "第一道口水鸡，第二道凉拌豆腐。",
            ),
        ],
    )

    outcome = harness.run(context)

    assert router.query == "凉拌豆腐的详细做法"
    assert outcome.context.retrieval_input == "凉拌豆腐的详细做法"
    assert outcome.context.conversation_context["resolution_source"] == "llm"
    resolution_event = next(
        event
        for event in outcome.result.events
        if event.get("type") == "context_resolution"
    )
    assert resolution_event["resolved_recipe_names"] == ["凉拌豆腐"]
    assert resolution_event["rewritten_query"] == "凉拌豆腐的详细做法"
    assert any(
        event.get("purpose") == "conversation_context_resolution"
        and event.get("llm_used") is True
        for event in outcome.result.events
    )


def test_harness_routes_follow_up_with_bounded_conversation_context() -> None:
    class _CapturingRouter:
        def __init__(self) -> None:
            self.query = ""

        def route(self, query: str) -> RouteDecision:
            self.query = query
            return RouteDecision(
                route=RouteType.SIMPLE,
                confidence=1.0,
                reason="capture only",
            )

    router = _CapturingRouter()
    harness = MultiExpertHarness(
        runtime_provider=lambda: (_ for _ in ()).throw(
            AssertionError("simple route must not initialize runtime")
        ),
        router=router,  # type: ignore[arg-type]
    )
    context = RunContext(
        user_id=1,
        session_id=1,
        session_public_id="context-session",
        original_input="那这个呢？",
        normalized_input="那这个呢？",
        profile=ProfileSnapshot(),
        history=[
            _message(MessageRole.USER, "凉皮怎么做？"),
            _message(MessageRole.ASSISTANT, "凉皮需要黄瓜丝。"),
        ],
    )

    outcome = harness.run(context)

    assert "那这个呢" in router.query
    assert "凉皮怎么做" in router.query
    assert outcome.context.routing_input == router.query
    assert "凉皮需要黄瓜丝" in outcome.context.retrieval_input
