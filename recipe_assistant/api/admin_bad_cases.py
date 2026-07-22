"""Authenticated developer API for Bad Case review and verification."""

from __future__ import annotations

import os
from dataclasses import dataclass
from secrets import compare_digest

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from recipe_assistant.api.dependencies import ApiContainer, get_container
from recipe_assistant.schemas.api.bad_case_admin import (
    ApproveBadCaseRequest,
    BadCaseDetailResponse,
    BadCaseSummaryResponse,
    ConfirmRegressionDraftRequest,
    MergeBadCaseRequest,
    RejectBadCaseRequest,
    ResolveBadCaseRequest,
    VerifyBadCaseRequest,
)
from recipe_assistant.services.evaluation import EvaluationService


router = APIRouter(prefix="/api/admin/bad-cases", tags=["admin-bad-cases"])


@dataclass(frozen=True, slots=True)
class AdminActor:
    actor_id: str


def require_admin(
    x_admin_id: str | None = Header(default=None, alias="X-Admin-Id", max_length=100),
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> AdminActor:
    configured_token = os.getenv("ADMIN_API_TOKEN", "")
    if not configured_token:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "admin API is disabled until ADMIN_API_TOKEN is configured",
        )
    if not x_admin_id or not x_admin_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "admin credentials are required")
    if not compare_digest(x_admin_token, configured_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid admin credentials")
    return AdminActor(actor_id=x_admin_id)


def get_evaluation_service(
    container: ApiContainer = Depends(get_container),
) -> EvaluationService:
    return EvaluationService(container.session_factory)


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("", response_model=list[BadCaseSummaryResponse])
def list_bad_cases(
    case_status: str | None = Query(default=None, alias="status"),
    _actor: AdminActor = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
) -> list[BadCaseSummaryResponse]:
    return service.list_candidates(case_status)


@router.get("/{bad_case_id}", response_model=BadCaseDetailResponse)
def get_bad_case(
    bad_case_id: int,
    _actor: AdminActor = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
) -> BadCaseDetailResponse:
    try:
        return service.get_detail(bad_case_id)
    except LookupError as exc:
        raise _translate_error(exc) from exc


@router.post("/{bad_case_id}/approve", response_model=BadCaseDetailResponse)
def approve_bad_case(
    bad_case_id: int,
    payload: ApproveBadCaseRequest,
    actor: AdminActor = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
) -> BadCaseDetailResponse:
    try:
        return service.approve(bad_case_id, actor.actor_id, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{bad_case_id}/reject", response_model=BadCaseDetailResponse)
def reject_bad_case(
    bad_case_id: int,
    payload: RejectBadCaseRequest,
    actor: AdminActor = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
) -> BadCaseDetailResponse:
    try:
        return service.reject(bad_case_id, actor.actor_id, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{bad_case_id}/merge", response_model=BadCaseDetailResponse)
def merge_bad_case(
    bad_case_id: int,
    payload: MergeBadCaseRequest,
    actor: AdminActor = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
) -> BadCaseDetailResponse:
    try:
        return service.merge(bad_case_id, actor.actor_id, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post(
    "/{bad_case_id}/regression-draft/confirm",
    response_model=BadCaseDetailResponse,
)
def confirm_regression_draft(
    bad_case_id: int,
    payload: ConfirmRegressionDraftRequest,
    actor: AdminActor = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
) -> BadCaseDetailResponse:
    try:
        return service.confirm_regression_draft(
            bad_case_id, actor.actor_id, payload
        )
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{bad_case_id}/resolve", response_model=BadCaseDetailResponse)
def resolve_bad_case(
    bad_case_id: int,
    payload: ResolveBadCaseRequest,
    actor: AdminActor = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
) -> BadCaseDetailResponse:
    try:
        return service.resolve(bad_case_id, actor.actor_id, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{bad_case_id}/verify", response_model=BadCaseDetailResponse)
def verify_bad_case(
    bad_case_id: int,
    payload: VerifyBadCaseRequest,
    actor: AdminActor = Depends(require_admin),
    service: EvaluationService = Depends(get_evaluation_service),
) -> BadCaseDetailResponse:
    try:
        return service.verify(bad_case_id, actor.actor_id, payload)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc
