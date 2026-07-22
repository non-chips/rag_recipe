from types import SimpleNamespace

from recipe_assistant.core.database import utc_now
from recipe_assistant.models import InteractionType
from recipe_assistant.schemas.nutrition import ConfirmedMealType
from recipe_assistant.services.meal_history import MealHistoryService


class _InteractionRepository:
    def __init__(self) -> None:
        now = utc_now()
        self.items = [
            SimpleNamespace(
                recipe_id="query-only",
                event_type=InteractionType.QUERY,
                servings=None,
                source="chat",
                confidence=None,
                occurred_at=now,
            ),
            SimpleNamespace(
                recipe_id="consumed",
                event_type=InteractionType.CONSUME,
                servings=1.5,
                source="user_confirmation",
                confidence=1.0,
                occurred_at=now,
            ),
            SimpleNamespace(
                recipe_id="cooked",
                event_type=InteractionType.COOK,
                servings=2,
                source="user_confirmation",
                confidence=1.0,
                occurred_at=now,
            ),
        ]
        self.requested_types = None

    def list_for_user(self, user_id, event_types=None):
        assert user_id == 3
        self.requested_types = event_types
        return [item for item in self.items if item.event_type in (event_types or set())]


def test_default_history_includes_only_consume_and_never_query() -> None:
    repository = _InteractionRepository()

    history = MealHistoryService(repository).load_confirmed(3)  # type: ignore[arg-type]

    assert repository.requested_types == {InteractionType.CONSUME}
    assert [record.recipe_id for record in history.records] == ["consumed"]
    assert history.included_event_types == (ConfirmedMealType.CONSUME,)


def test_confirmed_cook_requires_explicit_service_configuration() -> None:
    repository = _InteractionRepository()
    service = MealHistoryService(  # type: ignore[arg-type]
        repository,
        include_confirmed_cook=True,
    )

    history = service.load_confirmed(3)

    assert repository.requested_types == {
        InteractionType.CONSUME,
        InteractionType.COOK,
    }
    assert [record.recipe_id for record in history.records] == ["consumed", "cooked"]
    assert ConfirmedMealType.COOK in history.included_event_types

