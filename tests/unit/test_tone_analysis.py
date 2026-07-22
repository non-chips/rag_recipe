from __future__ import annotations

from recipe_assistant.schemas.feedback import ToneAnalysisRequest
from recipe_assistant.services.tone_analysis import ToneAnalysisService


def test_detects_retry_repeated_request_and_repeated_constraint_with_evidence() -> None:
    signal = ToneAnalysisService().analyze(
        ToneAnalysisRequest(
            current_text="我说过不要放花生，请重新回答，不要废话。",
            recent_user_messages=("请推荐一道不要放花生的家常菜",),
            current_constraints=("不要放花生",),
            recent_constraints=("不要放花生",),
        )
    )

    assert signal.requested_retry is True
    assert signal.repeated_constraint is True
    assert signal.possible_impatience > 0.7
    assert signal.confidence < 1.0
    assert any("retry phrase" in item for item in signal.evidence)


def test_exact_repeated_question_is_a_weak_signal_not_a_personality_label() -> None:
    signal = ToneAnalysisService().analyze(
        ToneAnalysisRequest(
            current_text="宫保鸡丁怎么做？",
            recent_user_messages=("宫保鸡丁怎么做",),
        )
    )

    assert signal.repeated_request is True
    assert signal.possible_frustration == 0.05
    assert signal.possible_dissatisfaction == 0.05
    assert signal.evidence == ("current request closely matches a recent request",)


def test_single_ambiguous_sentence_keeps_probabilities_conservative() -> None:
    signal = ToneAnalysisService().analyze(
        ToneAnalysisRequest(current_text="这个方案我不太喜欢，可以换一个吗？")
    )

    assert signal.explicit_error_reported is False
    assert signal.possible_frustration < 0.6
    assert signal.possible_impatience < 0.6
    assert signal.confidence <= 0.45
