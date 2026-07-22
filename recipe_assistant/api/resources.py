"""Basic session, profile, meal, report and trace HTTP resources."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from recipe_assistant.api.dependencies import ApiContainer, get_container, get_user_id
from recipe_assistant.schemas.api import (
    AgentRunTraceRead,
    ChatMessageRead,
    ChatSessionRead,
    MealConfirmRequest,
    NutritionReportRead,
    NutritionReportRequest,
    RecipeInteractionRead,
    UserProfileRead,
    UserProfileUpdate,
)


router = APIRouter(prefix="/api", tags=["resources"])


def _not_found(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/sessions", response_model=list[ChatSessionRead])
def list_sessions(
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> list[ChatSessionRead]:
    try:
        values = container.application.list_sessions(user_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    return [ChatSessionRead.model_validate(item) for item in values]


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[ChatMessageRead],
)
def list_messages(
    session_id: str,
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> list[ChatMessageRead]:
    try:
        values = container.application.list_messages(user_id, session_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    return [ChatMessageRead.model_validate(item) for item in values]


@router.get("/profile", response_model=UserProfileRead)
def get_profile(
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> UserProfileRead:
    try:
        profile = container.application.get_profile(user_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    if profile is None:
        raise HTTPException(status_code=404, detail="user profile was not found")
    return UserProfileRead.model_validate(profile)


@router.patch("/profile", response_model=UserProfileRead)
def update_profile(
    payload: UserProfileUpdate,
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> UserProfileRead:
    try:
        profile = container.application.update_profile(user_id, payload)
    except LookupError as exc:
        raise _not_found(exc) from exc
    return UserProfileRead.model_validate(profile)


@router.post(
    "/meals/confirm",
    response_model=RecipeInteractionRead,
    status_code=status.HTTP_201_CREATED,
)
def confirm_meal(
    payload: MealConfirmRequest,
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> RecipeInteractionRead:
    try:
        value = container.application.confirm_meal(user_id, payload)
    except LookupError as exc:
        raise _not_found(exc) from exc
    return RecipeInteractionRead.model_validate(value)


@router.get("/meals", response_model=list[RecipeInteractionRead])
def list_meals(
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> list[RecipeInteractionRead]:
    try:
        values = container.application.list_meals(user_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    return [RecipeInteractionRead.model_validate(item) for item in values]


@router.post("/reports/nutrition", response_model=NutritionReportRead)
def create_report(
    payload: NutritionReportRequest,
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> NutritionReportRead:
    try:
        report = container.application.create_nutrition_report(
            user_id,
            title=payload.title,
            days=payload.days,
        )
    except LookupError as exc:
        raise _not_found(exc) from exc
    return NutritionReportRead(report=report)


@router.get(
    "/reports/nutrition/{report_id}",
    response_model=NutritionReportRead,
)
def get_report(
    report_id: str,
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> NutritionReportRead:
    try:
        report = container.application.get_nutrition_report(user_id, report_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    return NutritionReportRead(report=report)


@router.get("/agent/runs/{run_id}", response_model=AgentRunTraceRead)
def get_trace(
    run_id: str,
    user_id: int = Depends(get_user_id),
    container: ApiContainer = Depends(get_container),
) -> AgentRunTraceRead:
    try:
        trace = container.application.get_trace(user_id, run_id)
    except LookupError as exc:
        raise _not_found(exc) from exc
    return AgentRunTraceRead.model_validate(trace)

