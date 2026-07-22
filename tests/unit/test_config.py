from pathlib import Path

from pydantic import SecretStr

from recipe_assistant.core.config import Settings


def test_settings_load_environment_and_feature_flags(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "offline-secret")
    monkeypatch.setenv("NEO4J_ENABLED", "true")
    monkeypatch.setenv("REDIS_ENABLED", "false")
    monkeypatch.setenv("MCP_ENABLED", "false")
    monkeypatch.setenv("EMBEDDING_MODEL_PATH", "tests/fixtures/embedding")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.chat_api_key == SecretStr("offline-secret")
    assert settings.neo4j_enabled is True
    assert settings.redis_enabled is False
    assert settings.mcp_enabled is False
    assert settings.embedding_model_path == Path("tests/fixtures/embedding")


def test_optional_services_are_disabled_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.neo4j_enabled is False
    assert settings.redis_enabled is False
    assert settings.mcp_enabled is False


def test_secret_values_are_masked_in_repr(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_API_KEY", "must-not-leak")

    settings = Settings(_env_file=None)

    assert "must-not-leak" not in repr(settings)
    assert "**********" in repr(settings.chat_api_key)


def test_chat_api_key_accepts_new_name_before_legacy_name(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_API_KEY", "new-name")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-name")

    settings = Settings(_env_file=None)

    assert settings.chat_api_key == SecretStr("new-name")
