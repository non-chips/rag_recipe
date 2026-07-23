from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Environment-backed configuration for the V2 application boundary."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    agent_runtime_mode: Literal["v2"] = "v2"
    legacy_fallback_enabled: Literal[False] = False

    chat_enabled: bool = True
    chat_model: str = "deepseek-v4-flash"
    chat_base_url: str = "https://api.deepseek.com"
    chat_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CHAT_API_KEY", "DEEPSEEK_API_KEY"),
    )
    chat_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    chat_timeout_seconds: float = Field(default=60.0, gt=0.0)
    chat_max_retries: int = Field(default=2, ge=0)

    embedding_enabled: bool = True
    embedding_model_path: Path = Path("model/embeddingmodels/bge-small-zh-v1.5")
    embedding_device: str = "cpu"
    embedding_offline: bool = True

    chroma_enabled: bool = True
    chroma_collection_name: str = "recipe_chunks"
    chroma_persist_dir: Path = Path("storage/chroma_db")

    bm25_enabled: bool = True

    neo4j_enabled: bool = False
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_username: str = "neo4j"
    neo4j_password: SecretStr | None = None
    neo4j_database: str = "neo4j"
    neo4j_connect_timeout_seconds: float = Field(default=10.0, gt=0.0)

    redis_enabled: bool = False
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")

    mcp_enabled: bool = False

    weather_enabled: bool = True
    amap_api_key: SecretStr | None = None
    amap_base_url: str = "https://restapi.amap.com"
    amap_timeout_seconds: float = Field(default=8.0, gt=0.0)

    def resolve_project_path(self, value: Path) -> Path:
        """Resolve a configured local path without requiring the process CWD."""

        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide immutable-by-convention settings instance."""

    return Settings()
