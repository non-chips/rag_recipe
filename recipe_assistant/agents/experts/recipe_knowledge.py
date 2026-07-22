"""Evidence-grounded recipe knowledge expert."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, ClassVar

from pydantic import Field

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ExpertCapability,
)
from recipe_assistant.agents.experts.base import BaseExpert, ExpertPayload
from recipe_assistant.agents.prompts import INSUFFICIENT_RECIPE_EVIDENCE_MESSAGE
from recipe_assistant.schemas.retrieval import RetrievalResult
from recipe_assistant.tools.schemas import ToolRole


class KnowledgeTopic(str, Enum):
    INGREDIENTS = "ingredients"
    STEPS = "steps"
    TOOLS = "tools"
    COMPARISON = "comparison"
    SUBSTITUTION = "substitution"
    GENERAL = "general"


class KnowledgeConstraints(ExpertPayload):
    query: str = Field(min_length=1)
    topics: tuple[KnowledgeTopic, ...]
    recipe_names: tuple[str, ...] = ()
    include_ingredients: tuple[str, ...] = ()
    exclude_ingredients: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()


class RecipeEvidenceItem(ExpertPayload):
    recipe_id: str = Field(min_length=1)
    recipe_name: str | None = None
    content: str = Field(min_length=1)
    source_path: str = ""
    retrieval_sources: tuple[str, ...] = ()


class RecipeEvidence(ExpertPayload):
    query: str = Field(min_length=1)
    items: tuple[RecipeEvidenceItem, ...] = ()
    retrieval_confidence: float = Field(ge=0.0, le=1.0)
    warnings: tuple[str, ...] = ()
    sufficient: bool
    degraded: bool


class EvidenceValidation(ExpertPayload):
    sufficient: bool
    evidence_count: int = Field(ge=0)
    covered_topics: tuple[KnowledgeTopic, ...] = ()
    missing_topics: tuple[KnowledgeTopic, ...] = ()
    warnings: tuple[str, ...] = ()


class ResponsePlan(ExpertPayload):
    answer_mode: str
    message: str
    topics: tuple[KnowledgeTopic, ...] = ()
    evidence: tuple[RecipeEvidenceItem, ...] = ()
    source_paths: tuple[str, ...] = ()
    grounded_only: bool = True
    degraded: bool = False


class RecipeKnowledgeExpert(BaseExpert):
    """Use only recipe knowledge tools and publish evidence-grounded artifacts."""

    name: ClassVar[str] = "recipe_knowledge_expert"
    capabilities: ClassVar[frozenset[ExpertCapability]] = frozenset(
        {ExpertCapability.RECIPE_KNOWLEDGE}
    )
    _SEARCH_TOOL = "search_recipe_knowledge"

    def execute(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> AgentArtifact:
        if task.capability not in self.capabilities:
            raise ValueError(f"unsupported capability: {task.capability.value}")
        handlers = {
            "ExtractConstraints": self._extract_constraints,
            "RetrieveRecipeKnowledge": self._retrieve,
            "EvidenceCheck": self._check_evidence,
            "BuildResponsePlan": self._build_response_plan,
        }
        try:
            handler = handlers[task.title]
        except KeyError as exc:
            raise ValueError(f"unsupported knowledge task: {task.title}") from exc
        return handler(task, blackboard)

    def _extract_constraints(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        constraints = KnowledgeConstraints(
            query=board.user_input,
            topics=self._classify_topics(board.user_input),
        )
        return self._artifact(task, board, ArtifactKind.QUERY_CONSTRAINTS, constraints, 1.0)

    def _retrieve(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        constraints = self._constraints(board)
        invocation = self.tool_registry.invoke(
            role=ToolRole.KNOWLEDGE_EXPERT,
            tool_name=self._SEARCH_TOOL,
            arguments={
                "query": constraints.query,
                "recipe_names": list(constraints.recipe_names),
                "include_ingredients": list(constraints.include_ingredients),
                "exclude_ingredients": list(constraints.exclude_ingredients),
                "tools": list(constraints.tools),
                "top_k": 5,
            },
            context=self.tool_context(board),
        )
        result = RetrievalResult.model_validate(invocation.output)
        items = tuple(
            RecipeEvidenceItem(
                recipe_id=hit.recipe_id,
                recipe_name=hit.recipe_name,
                content=hit.content,
                source_path=hit.source_path,
                retrieval_sources=tuple(hit.retrieval_sources),
            )
            for hit in result.hits
        )
        evidence = RecipeEvidence(
            query=result.query,
            items=items,
            retrieval_confidence=result.confidence,
            warnings=tuple(result.warnings),
            sufficient=bool(items),
            degraded=not items,
        )
        return self._artifact(
            task,
            board,
            ArtifactKind.RECIPE_EVIDENCE,
            evidence,
            result.confidence,
            degraded=evidence.degraded,
            trace_id=invocation.trace_id,
        )

    def _check_evidence(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        constraints = self._constraints(board)
        evidence = self._evidence(board)
        validation = EvidenceValidation(
            sufficient=evidence.sufficient,
            evidence_count=len(evidence.items),
            covered_topics=constraints.topics if evidence.sufficient else (),
            missing_topics=() if evidence.sufficient else constraints.topics,
            warnings=evidence.warnings,
        )
        confidence = evidence.retrieval_confidence if validation.sufficient else 0.0
        return self._artifact(
            task,
            board,
            ArtifactKind.CONSTRAINT_VALIDATION,
            validation,
            confidence,
            degraded=not validation.sufficient,
        )

    def _build_response_plan(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        constraints = self._constraints(board)
        evidence = self._evidence(board)
        validation = self._validation(board)
        if validation.sufficient:
            plan = ResponsePlan(
                answer_mode="evidence_grounded_recipe_knowledge",
                message="请仅依据 evidence 字段回答，并按用户所问的食材、步骤、厨具、比较或替换维度组织内容。",
                topics=constraints.topics,
                evidence=evidence.items,
                source_paths=tuple(
                    dict.fromkeys(item.source_path for item in evidence.items if item.source_path)
                ),
            )
            confidence = evidence.retrieval_confidence
        else:
            plan = ResponsePlan(
                answer_mode="insufficient_evidence",
                message=INSUFFICIENT_RECIPE_EVIDENCE_MESSAGE,
                topics=constraints.topics,
                degraded=True,
            )
            confidence = 0.0
        return self._artifact(
            task,
            board,
            ArtifactKind.RESPONSE_PLAN,
            plan,
            confidence,
            degraded=plan.degraded,
        )

    def _artifact(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
        kind: ArtifactKind,
        payload: ExpertPayload,
        confidence: float,
        **metadata: Any,
    ) -> AgentArtifact:
        return AgentArtifact(
            id=self.artifact_id(board, task),
            owner=self.name,
            kind=kind,
            payload=payload.model_dump(mode="python"),
            confidence=confidence,
            task_id=task.id,
            metadata=metadata,
        )

    @staticmethod
    def _classify_topics(query: str) -> tuple[KnowledgeTopic, ...]:
        patterns = (
            (KnowledgeTopic.INGREDIENTS, r"食材|材料|配料|用料"),
            (KnowledgeTopic.STEPS, r"步骤|做法|怎么做|如何做|制作"),
            (KnowledgeTopic.TOOLS, r"厨具|工具|锅|烤箱|空气炸锅"),
            (KnowledgeTopic.COMPARISON, r"比较|对比|区别|不同|哪个好|还是"),
            (KnowledgeTopic.SUBSTITUTION, r"替代|替换|代替|没有.+可以"),
        )
        topics = tuple(topic for topic, pattern in patterns if re.search(pattern, query))
        return topics or (KnowledgeTopic.GENERAL,)

    @staticmethod
    def _latest_payload(
        board: CollaborationBlackboard,
        kind: ArtifactKind,
        schema: type[ExpertPayload],
    ) -> ExpertPayload:
        artifacts = board.artifacts_for(kind=kind)
        if not artifacts:
            raise ValueError(f"required artifact is missing: {kind.value}")
        return schema.model_validate(artifacts[-1].payload)

    def _constraints(self, board: CollaborationBlackboard) -> KnowledgeConstraints:
        payload = self._latest_payload(board, ArtifactKind.QUERY_CONSTRAINTS, KnowledgeConstraints)
        assert isinstance(payload, KnowledgeConstraints)
        return payload

    def _evidence(self, board: CollaborationBlackboard) -> RecipeEvidence:
        payload = self._latest_payload(board, ArtifactKind.RECIPE_EVIDENCE, RecipeEvidence)
        assert isinstance(payload, RecipeEvidence)
        return payload

    def _validation(self, board: CollaborationBlackboard) -> EvidenceValidation:
        payload = self._latest_payload(
            board,
            ArtifactKind.CONSTRAINT_VALIDATION,
            EvidenceValidation,
        )
        assert isinstance(payload, EvidenceValidation)
        return payload

