"""FastAPI application entry point."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from recipe_assistant.api.dependencies import ApiContainer
from recipe_assistant.api.router import api_router


def create_app(
    container_factory: Callable[[], ApiContainer] | None = None,
) -> FastAPI:
    factory = container_factory or ApiContainer.build_default

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        container = factory()
        container.startup()
        app.state.container = container
        try:
            yield
        finally:
            container.shutdown()

    application = FastAPI(
        title="Recipe Assistant API",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.include_router(api_router)
    return application


app = create_app()
