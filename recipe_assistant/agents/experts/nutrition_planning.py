"""Source-aware nutrition planning expert."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from recipe_assistant.agents.blackboard import CollaborationBlackboard
from recipe_assistant.agents.events import (
    AgentArtifact,
    AgentTask,
    ArtifactKind,
    ExpertCapability,
)
from recipe_assistant.agents.experts.base import BaseExpert
from recipe_assistant.schemas.nutrition import (
    ConfirmedMealHistory,
    NutritionGoal,
    NutritionReport,
    NutritionSummary,
)
from recipe_assistant.services.nutrition import NutritionService
from recipe_assistant.services.report import ReportService
from recipe_assistant.tools.context import ToolContext
from recipe_assistant.tools.registry import ToolRegistry
from recipe_assistant.tools.schemas import ToolRole


class NutritionResponsePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    answer_mode: str
    report_id: str
    message: str
    precise_metrics_available: bool
    medical_advice: bool = False
    degraded: bool = False


class NutritionPlanningExpert(BaseExpert):
    """Plan from confirmed meals without creating medical conclusions."""

    name: ClassVar[str] = "nutrition_planning_expert"
    capabilities: ClassVar[frozenset[ExpertCapability]] = frozenset(
        {ExpertCapability.NUTRITION_PLANNING}
    )

    def __init__(
        self,
        tool_registry: ToolRegistry,
        *,
        report_service: ReportService | None = None,
    ) -> None:
        super().__init__(tool_registry)
        self.report_service = report_service or ReportService()

    def execute(
        self,
        task: AgentTask,
        blackboard: CollaborationBlackboard,
    ) -> AgentArtifact | tuple[AgentArtifact, ...]:
        if task.capability not in self.capabilities:
            raise ValueError(f"unsupported capability: {task.capability.value}")
        handlers = {
            "LoadConfirmedMealHistory": self._load_history,
            "CalculateNutritionSummary": self._calculate_summary,
            "BuildNutritionGuidance": self._build_guidance,
            "BuildResponsePlan": self._build_response_plan,
            "NutritionPlanningExpert": self._build_complex_goal,
        }
        try:
            return handlers[task.title](task, blackboard)
        except KeyError as exc:
            raise ValueError(f"unsupported nutrition task: {task.title}") from exc

    def tool_context(self, blackboard: CollaborationBlackboard) -> ToolContext:
        return ToolContext(
            run_id=blackboard.run_id,
            user_id=blackboard.user_id,
            session_id=blackboard.session_id,
            route=blackboard.route.route.value,
            permissions=frozenset({"user_data:read"}),
        )

    def _load_history(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        history, trace_id = self._load_history_from_tool(board)
        return self._artifact(
            task,
            board,
            ArtifactKind.MEAL_HISTORY,
            history,
            1.0 if history.records else 0.0,
            degraded=not history.records,
            trace_id=trace_id,
        )

    def _calculate_summary(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        history = self._history(board)
        summary, trace_id = self._summary_from_tool(history, board)
        return self._artifact(
            task,
            board,
            ArtifactKind.NUTRITION_SUMMARY,
            summary,
            summary.data_coverage,
            degraded=not summary.precise_metrics_available,
            trace_id=trace_id,
        )

    def _build_guidance(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        goal = NutritionService.build_goal(self._summary(board))
        return self._artifact(
            task,
            board,
            ArtifactKind.NUTRITION_GOAL,
            goal,
            1.0 if goal.based_on_confirmed_meals else 0.0,
            degraded=not goal.based_on_confirmed_meals,
        )

    def _build_response_plan(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> tuple[AgentArtifact, AgentArtifact]:
        history = self._history(board)
        summary = self._summary(board)
        goal = self._goal(board)
        report = self.report_service.create_draft(
            run_id=board.run_id,
            title="确认饮食记录营养概览",
            history=history,
            summary=summary,
            goal=goal,
        )
        report_artifact = self._artifact(
            task,
            board,
            ArtifactKind.REPORT_DRAFT,
            report,
            summary.data_coverage,
            degraded=not summary.precise_metrics_available,
        )
        plan = NutritionResponsePlan(
            answer_mode=(
                "source_aware_nutrition_overview"
                if summary.precise_metrics_available
                else "food_category_diversity_only"
            ),
            report_id=report.report_id,
            message=(
                "仅依据 JSON 报告中的确认记录、来源、质量和覆盖率说明营养概览；不得扩展为医疗诊断。"
            ),
            precise_metrics_available=summary.precise_metrics_available,
            degraded=not summary.precise_metrics_available,
        )
        plan_artifact = self._artifact(
            task,
            board,
            ArtifactKind.RESPONSE_PLAN,
            plan,
            summary.data_coverage,
            degraded=plan.degraded,
        )
        return report_artifact, plan_artifact

    def _build_complex_goal(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
    ) -> AgentArtifact:
        history, history_trace = self._load_history_from_tool(board)
        summary, summary_trace = self._summary_from_tool(history, board)
        goal = NutritionService.build_goal(summary)
        return self._artifact(
            task,
            board,
            ArtifactKind.NUTRITION_GOAL,
            goal,
            summary.data_coverage,
            degraded=not summary.precise_metrics_available,
            trace_ids=(history_trace, summary_trace),
        )

    def _load_history_from_tool(
        self,
        board: CollaborationBlackboard,
    ) -> tuple[ConfirmedMealHistory, str]:
        invocation = self.tool_registry.invoke(
            role=ToolRole.NUTRITION_EXPERT,
            tool_name="get_confirmed_meal_history",
            arguments={"days": 7},
            context=self.tool_context(board),
        )
        return ConfirmedMealHistory.model_validate(invocation.output), invocation.trace_id

    def _summary_from_tool(
        self,
        history: ConfirmedMealHistory,
        board: CollaborationBlackboard,
    ) -> tuple[NutritionSummary, str]:
        recipe_ids = list(dict.fromkeys(record.recipe_id for record in history.records))
        if not recipe_ids:
            return NutritionService.build_empty_summary(), ""
        invocation = self.tool_registry.invoke(
            role=ToolRole.NUTRITION_EXPERT,
            tool_name="calculate_recipe_nutrition",
            arguments={"recipe_ids": recipe_ids},
            context=self.tool_context(board),
        )
        return NutritionSummary.model_validate(invocation.output), invocation.trace_id

    def _artifact(
        self,
        task: AgentTask,
        board: CollaborationBlackboard,
        kind: ArtifactKind,
        payload: BaseModel,
        confidence: float,
        **metadata: Any,
    ) -> AgentArtifact:
        return AgentArtifact(
            id=f"{self.artifact_id(board, task)}:{kind.value.lower()}",
            owner=self.name,
            kind=kind,
            payload=payload.model_dump(mode="python"),
            confidence=confidence,
            task_id=task.id,
            metadata=metadata,
        )

    @staticmethod
    def _latest(
        board: CollaborationBlackboard,
        kind: ArtifactKind,
        schema: type[BaseModel],
    ) -> BaseModel:
        artifacts = board.artifacts_for(kind=kind)
        if not artifacts:
            raise ValueError(f"required artifact is missing: {kind.value}")
        return schema.model_validate(artifacts[-1].payload)

    def _history(self, board: CollaborationBlackboard) -> ConfirmedMealHistory:
        value = self._latest(board, ArtifactKind.MEAL_HISTORY, ConfirmedMealHistory)
        assert isinstance(value, ConfirmedMealHistory)
        return value

    def _summary(self, board: CollaborationBlackboard) -> NutritionSummary:
        value = self._latest(board, ArtifactKind.NUTRITION_SUMMARY, NutritionSummary)
        assert isinstance(value, NutritionSummary)
        return value

    def _goal(self, board: CollaborationBlackboard) -> NutritionGoal:
        value = self._latest(board, ArtifactKind.NUTRITION_GOAL, NutritionGoal)
        assert isinstance(value, NutritionGoal)
        return value

