"""Read only explicitly confirmed meal interactions."""

from __future__ import annotations

from datetime import datetime, timedelta

from recipe_assistant.core.database import utc_now
from recipe_assistant.models import InteractionType
from recipe_assistant.repositories.interfaces import InteractionRepository
from recipe_assistant.schemas.nutrition import (
    ConfirmedMealHistory,
    ConfirmedMealRecord,
    ConfirmedMealType,
)


class MealHistoryService:
    """Load CONSUME records and optionally explicitly recorded COOK events."""

    def __init__(
        self,
        repository: InteractionRepository,
        *,
        include_confirmed_cook: bool = False,
    ) -> None:
        self.repository = repository
        self.include_confirmed_cook = include_confirmed_cook

    def load_confirmed(
        self,
        user_id: int,
        *,
        days: int = 7,
        now: datetime | None = None,
    ) -> ConfirmedMealHistory:
        if days < 1:
            raise ValueError("days must be positive")
        end_at = now or utc_now()
        if end_at.tzinfo is None or end_at.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        start_at = end_at - timedelta(days=days)
        event_types = {InteractionType.CONSUME}
        included = [ConfirmedMealType.CONSUME]
        if self.include_confirmed_cook:
            event_types.add(InteractionType.COOK)
            included.append(ConfirmedMealType.COOK)
        interactions = self.repository.list_for_user(user_id, event_types=event_types)
        records = tuple(
            ConfirmedMealRecord(
                recipe_id=item.recipe_id,
                event_type=ConfirmedMealType(item.event_type.value),
                servings=item.servings,
                source=item.source or "",
                confidence=item.confidence,
                occurred_at=item.occurred_at,
            )
            for item in interactions
            if start_at <= item.occurred_at <= end_at
        )
        return ConfirmedMealHistory(
            user_id=user_id,
            records=records,
            included_event_types=tuple(included),
            start_at=start_at,
            end_at=end_at,
        )

