from pathlib import Path

from recipe_assistant.main import create_app


def test_openapi_exposes_required_basic_resources() -> None:
    paths = create_app().openapi()["paths"]
    required = {
        "/actuator/health",
        "/api/chat/stream",
        "/api/sessions",
        "/api/sessions/{session_id}/messages",
        "/api/profile",
        "/api/meals/confirm",
        "/api/meals",
        "/api/reports/nutrition",
        "/api/reports/nutrition/{report_id}",
        "/api/agent/runs/{run_id}",
    }

    assert required.issubset(paths)
    assert paths["/api/chat/stream"]["post"]["responses"]["200"]["content"][
        "text/event-stream"
    ]


def test_streamlit_client_has_no_backend_business_imports() -> None:
    source = Path("frontend/streamlit_app.py").read_text(encoding="utf-8")

    assert "FRONTEND_API_BASE_URL" in source
    assert "/api/chat/stream" in source
    for forbidden in (
        "recipe_assistant.",
        "agent.react_agent",
        "agents.",
        "services.",
        "repositories.",
    ):
        assert forbidden not in source

