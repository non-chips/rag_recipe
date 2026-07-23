from recipe_assistant.agents.factory import MultiExpertHarness, build_runtime_harness
from recipe_assistant.core.config import Settings
from recipe_assistant.core.database import (
    create_database_engine,
    create_session_factory,
)


def test_v2_harness_creation_is_offline() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        chat_enabled=False,
        embedding_enabled=False,
        chroma_enabled=False,
        bm25_enabled=False,
        neo4j_enabled=False,
        weather_enabled=False,
    )
    engine = create_database_engine("sqlite:///:memory:")
    harness = build_runtime_harness(settings, create_session_factory(engine))
    engine.dispose()

    assert isinstance(harness, MultiExpertHarness)
    assert harness.mode == "v2"
