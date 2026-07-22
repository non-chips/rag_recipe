"""Health endpoint reporting optional components without forcing initialization."""

from fastapi import APIRouter, Depends

from recipe_assistant.api.dependencies import ApiContainer, get_container
from recipe_assistant.core.container import ResourceName
from recipe_assistant.schemas.api import HealthComponent, HealthResponse


router = APIRouter(tags=["health"])


@router.get("/actuator/health", response_model=HealthResponse)
def health(container: ApiContainer = Depends(get_container)) -> HealthResponse:
    components = {
        "database": HealthComponent(
            status="UP" if container.started else "DOWN",
            detail="SQLite lifecycle initialized" if container.started else "not started",
        )
    }
    if container.resources is not None:
        for name in ResourceName:
            enabled = container.resources.is_enabled(name)
            components[name.value] = HealthComponent(
                status="DEGRADED" if enabled else "DISABLED",
                detail="enabled; initialized lazily" if enabled else "disabled by configuration",
            )
        settings = container.resources.settings
        for name, enabled in {
            "weather": settings.weather_enabled,
            "redis": settings.redis_enabled,
            "mcp": settings.mcp_enabled,
        }.items():
            components[name] = HealthComponent(
                status="DEGRADED" if enabled else "DISABLED",
                detail="enabled; connectivity not probed" if enabled else "disabled",
            )
    overall = "DOWN" if components["database"].status == "DOWN" else "UP"
    return HealthResponse(status=overall, components=components)

