"""Top-level API router."""

from fastapi import APIRouter

from recipe_assistant.api.admin_bad_cases import router as admin_bad_cases_router
from recipe_assistant.api.chat import router as chat_router
from recipe_assistant.api.feedback import router as feedback_router
from recipe_assistant.api.health import router as health_router
from recipe_assistant.api.resources import router as resources_router


api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(chat_router)
api_router.include_router(resources_router)
api_router.include_router(feedback_router)
api_router.include_router(admin_bad_cases_router)

