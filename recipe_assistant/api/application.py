"""Application-facing persistence operations used by HTTP routers."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from recipe_assistant.core.database import session_scope
from recipe_assistant.models import AgentRunTrace, ChatSession, InteractionType, UserProfile
from recipe_assistant.repositories.sqlite import (
    SqlAlchemyChatRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyProfileRepository,
    SqlAlchemyTraceRepository,
    SqlAlchemyUserRepository,
)
from recipe_assistant.schemas.api import MealConfirmRequest, UserProfileUpdate
from recipe_assistant.schemas.nutrition import NutritionReport
from recipe_assistant.services.meal_history import MealHistoryService
from recipe_assistant.services.nutrition import NutritionCatalog, NutritionService
from recipe_assistant.services.report import ReportService


class ApiApplicationService:
    """Keep database and nutrition composition out of FastAPI route functions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        nutrition_catalog: NutritionCatalog,
    ) -> None:
        self.session_factory = session_factory
        self.nutrition_catalog = nutrition_catalog
        self._reports: dict[tuple[int, str], NutritionReport] = {}

    def list_sessions(self, user_id: int) -> list[ChatSession]:
        with session_scope(self.session_factory) as session:
            self._require_user(session, user_id)
            statement = (
                select(ChatSession)
                .where(ChatSession.user_id == user_id)
                .order_by(ChatSession.updated_at.desc(), ChatSession.id.desc())
            )
            return list(session.scalars(statement))

    def list_messages(self, user_id: int, public_id: str):
        with session_scope(self.session_factory) as session:
            repository = SqlAlchemyChatRepository(session)
            chat_session = repository.get_session_by_public_id(public_id)
            if chat_session is None or chat_session.user_id != user_id:
                raise LookupError("chat session was not found")
            return repository.list_messages(chat_session.id)

    def get_profile(self, user_id: int) -> UserProfile | None:
        with session_scope(self.session_factory) as session:
            self._require_user(session, user_id)
            return SqlAlchemyProfileRepository(session).get(user_id)

    def update_profile(self, user_id: int, payload: UserProfileUpdate) -> UserProfile:
        with session_scope(self.session_factory) as session:
            self._require_user(session, user_id)
            values = payload.model_dump()
            return SqlAlchemyProfileRepository(session).upsert(
                user_id,
                preferred_cuisines_json=values["preferred_cuisines"],
                disliked_ingredients_json=values["disliked_ingredients"],
                allergens_json=values["allergens"],
                available_appliances_json=values["available_appliances"],
                default_servings=values["default_servings"],
                skill_level=values["skill_level"],
                planning_goal=values["planning_goal"],
            )

    def confirm_meal(self, user_id: int, payload: MealConfirmRequest):
        with session_scope(self.session_factory) as session:
            self._require_user(session, user_id)
            return SqlAlchemyInteractionRepository(session).add(
                user_id=user_id,
                recipe_id=payload.recipe_id,
                event_type=InteractionType(payload.event_type),
                servings=payload.servings,
                source=payload.source,
                confidence=1.0,
                occurred_at=payload.occurred_at,
            )

    def list_meals(self, user_id: int):
        with session_scope(self.session_factory) as session:
            self._require_user(session, user_id)
            return SqlAlchemyInteractionRepository(session).list_for_user(
                user_id,
                event_types={InteractionType.CONSUME, InteractionType.COOK},
            )

    def create_nutrition_report(
        self,
        user_id: int,
        *,
        title: str,
        days: int,
    ) -> NutritionReport:
        with session_scope(self.session_factory) as session:
            self._require_user(session, user_id)
            history = MealHistoryService(
                SqlAlchemyInteractionRepository(session)
            ).load_confirmed(user_id, days=days)
        summary = NutritionService(self.nutrition_catalog).summarize(history)
        goal = NutritionService.build_goal(summary)
        report = ReportService().create_draft(
            run_id=f"api-{uuid4().hex}",
            title=title,
            history=history,
            summary=summary,
            goal=goal,
        )
        self._reports[(user_id, report.report_id)] = report
        return report

    def get_nutrition_report(self, user_id: int, report_id: str) -> NutritionReport:
        try:
            return self._reports[(user_id, report_id)]
        except KeyError as exc:
            raise LookupError("nutrition report was not found") from exc

    def get_trace(self, user_id: int, run_id: str) -> AgentRunTrace:
        with session_scope(self.session_factory) as session:
            trace = SqlAlchemyTraceRepository(session).get_by_run_id(run_id)
            if trace is None or trace.user_id != user_id:
                raise LookupError("agent run was not found")
            return trace

    @staticmethod
    def _require_user(session: Session, user_id: int) -> None:
        if SqlAlchemyUserRepository(session).get(user_id) is None:
            raise LookupError("user was not found")

