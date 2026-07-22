"""HTTP endpoints for explicit answer feedback."""

from fastapi import APIRouter, Depends, HTTPException, status

from recipe_assistant.api.dependencies import ApiContainer, get_container, get_user_id
from recipe_assistant.schemas.feedback import AnswerFeedbackRequest, AnswerFeedbackResponse
from recipe_assistant.services.feedback import FeedbackService


router = APIRouter(prefix="/api/feedback", tags=["feedback"])


def get_feedback_service(
    container: ApiContainer = Depends(get_container),
) -> FeedbackService:
    return FeedbackService(container.session_factory)


@router.post("", response_model=AnswerFeedbackResponse)
def submit_feedback(
    payload: AnswerFeedbackRequest,
    user_id: int = Depends(get_user_id),
    service: FeedbackService = Depends(get_feedback_service),
) -> AnswerFeedbackResponse:
    try:
        return service.submit(user_id, payload)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.get("/{message_id}", response_model=AnswerFeedbackResponse)
def get_feedback(
    message_id: int,
    user_id: int = Depends(get_user_id),
    service: FeedbackService = Depends(get_feedback_service),
) -> AnswerFeedbackResponse:
    try:
        return service.get(user_id, message_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
