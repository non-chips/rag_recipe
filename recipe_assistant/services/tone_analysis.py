"""Conservative, rule-first analysis of interaction-level weak signals."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from recipe_assistant.schemas.feedback import ToneAnalysisRequest, ToneSignal


_RETRY_PHRASES = ("重新回答", "重答", "再回答", "再说一次", "答非所问", "try again", "answer again")
_ERROR_PHRASES = ("回答错", "说错", "不正确", "这是错", "有错误", "wrong answer", "incorrect")
_DISSATISFACTION_PHRASES = _ERROR_PHRASES + ("答非所问", "没用", "不是我要", "不满意")
_IMPATIENCE_PHRASES = ("不要废话", "直接说", "快点", "说重点", "简短点", "just answer", "hurry")


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text).casefold()


def _matches(text: str, phrases: tuple[str, ...]) -> list[str]:
    lowered = text.casefold()
    return [phrase for phrase in phrases if phrase.casefold() in lowered]


class ToneAnalysisService:
    """Return probabilities and evidence, never a permanent user label."""

    def __init__(self, repeated_similarity_threshold: float = 0.88) -> None:
        self.repeated_similarity_threshold = repeated_similarity_threshold

    def analyze(self, request: ToneAnalysisRequest) -> ToneSignal:
        text = request.current_text
        normalized = _normalize(text)
        recent = [_normalize(item) for item in request.recent_user_messages]
        repeated_request = bool(normalized) and any(
            previous
            and (
                normalized == previous
                or (
                    min(len(normalized), len(previous)) >= 6
                    and SequenceMatcher(None, normalized, previous).ratio()
                    >= self.repeated_similarity_threshold
                )
            )
            for previous in recent
        )

        current_constraints = {_normalize(item) for item in request.current_constraints}
        recent_constraints = {_normalize(item) for item in request.recent_constraints}
        repeated_constraint = bool(current_constraints & recent_constraints)

        retry_matches = _matches(text, _RETRY_PHRASES)
        error_matches = _matches(text, _ERROR_PHRASES)
        dissatisfaction_matches = _matches(text, _DISSATISFACTION_PHRASES)
        impatience_matches = _matches(text, _IMPATIENCE_PHRASES)
        evidence: list[str] = []
        if repeated_request:
            evidence.append("current request closely matches a recent request")
        if repeated_constraint:
            evidence.append("a current constraint matches a previously supplied constraint")
        evidence.extend(f"matched retry phrase: {phrase}" for phrase in retry_matches)
        evidence.extend(f"matched explicit error phrase: {phrase}" for phrase in error_matches)
        evidence.extend(
            f"matched dissatisfaction phrase: {phrase}"
            for phrase in dissatisfaction_matches
            if phrase not in error_matches
        )
        evidence.extend(f"matched brevity/impatience phrase: {phrase}" for phrase in impatience_matches)

        dissatisfaction = 0.05
        if dissatisfaction_matches:
            dissatisfaction = 0.78 if error_matches else 0.68
        impatience = 0.05 if not impatience_matches else 0.76
        frustration = 0.05
        if dissatisfaction_matches:
            frustration = 0.58
        if retry_matches and dissatisfaction_matches:
            frustration = 0.72
        confidence = min(0.95, 0.35 + 0.10 * len(evidence)) if evidence else 0.20
        return ToneSignal(
            possible_frustration=frustration,
            possible_impatience=impatience,
            possible_dissatisfaction=dissatisfaction,
            repeated_request=repeated_request,
            repeated_constraint=repeated_constraint,
            requested_retry=bool(retry_matches),
            explicit_error_reported=bool(error_matches),
            evidence=tuple(dict.fromkeys(evidence)),
            confidence=confidence,
        )
