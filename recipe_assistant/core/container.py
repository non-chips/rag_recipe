from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import RLock
from typing import Any

from recipe_assistant.core.config import Settings
from recipe_assistant.core.exceptions import (
    ConfigurationError,
    ResourceDisabledError,
    ResourceInitializationError,
    ResourceShutdownError,
)


class ResourceName(str, Enum):
    CHAT_MODEL = "chat_model"
    EMBEDDING = "embedding"
    CHROMA = "chroma"
    BM25 = "bm25"
    NEO4J = "neo4j"


ResourceFactory = Callable[["ResourceContainer"], Any]


@dataclass(frozen=True, slots=True)
class ResourceFactories:
    """Optional factory overrides used by tests and future infrastructure adapters."""

    chat_model: ResourceFactory | None = None
    embedding: ResourceFactory | None = None
    chroma: ResourceFactory | None = None
    bm25: ResourceFactory | None = None
    neo4j: ResourceFactory | None = None


class ResourceContainer:
    """Own and lazily reuse process-lifetime infrastructure resources."""

    def __init__(
        self,
        settings: Settings,
        factories: ResourceFactories | None = None,
    ) -> None:
        self.settings = settings
        self.factories = factories or ResourceFactories()
        self._resources: dict[ResourceName, Any] = {}
        self._creation_order: list[ResourceName] = []
        self._lock = RLock()
        self._started = False

    @property
    def started(self) -> bool:
        return self._started

    def startup(
        self,
        eager_resources: Iterable[ResourceName | str] = (),
    ) -> None:
        """Mark the container started and optionally prewarm selected resources."""

        with self._lock:
            self._started = True

        for resource_name in eager_resources:
            self.get(ResourceName(resource_name))

    def shutdown(self) -> None:
        """Close initialized resources once, in reverse creation order."""

        errors: list[str] = []

        with self._lock:
            for resource_name in reversed(self._creation_order):
                resource = self._resources.get(resource_name)
                if resource is None:
                    continue
                try:
                    self._close_resource(resource)
                except Exception as exc:  # cleanup must continue for remaining resources
                    errors.append(f"{resource_name.value}: {exc}")

            self._resources.clear()
            self._creation_order.clear()
            self._started = False

        if errors:
            raise ResourceShutdownError("; ".join(errors))

    def get(self, resource_name: ResourceName) -> Any:
        """Return a cached resource or build it exactly once for this container."""

        self._ensure_enabled(resource_name)

        with self._lock:
            if resource_name in self._resources:
                return self._resources[resource_name]

            factory = self._get_factory(resource_name)
            try:
                resource = factory(self)
            except (ConfigurationError, ResourceDisabledError):
                raise
            except Exception as exc:
                raise ResourceInitializationError(
                    f"Failed to initialize {resource_name.value}: {exc}"
                ) from exc

            self._resources[resource_name] = resource
            self._creation_order.append(resource_name)
            return resource

    def get_chat_model(self) -> Any:
        return self.get(ResourceName.CHAT_MODEL)

    def get_embedding(self) -> Any:
        return self.get(ResourceName.EMBEDDING)

    def get_chroma(self) -> Any:
        return self.get(ResourceName.CHROMA)

    def get_bm25(self) -> Any:
        return self.get(ResourceName.BM25)

    def get_neo4j(self) -> Any:
        return self.get(ResourceName.NEO4J)

    def is_enabled(self, resource_name: ResourceName | str) -> bool:
        name = ResourceName(resource_name)
        return {
            ResourceName.CHAT_MODEL: self.settings.chat_enabled,
            ResourceName.EMBEDDING: self.settings.embedding_enabled,
            ResourceName.CHROMA: self.settings.chroma_enabled,
            ResourceName.BM25: self.settings.bm25_enabled,
            ResourceName.NEO4J: self.settings.neo4j_enabled,
        }[name]

    def _ensure_enabled(self, resource_name: ResourceName) -> None:
        if not self.is_enabled(resource_name):
            raise ResourceDisabledError(
                f"Resource '{resource_name.value}' is disabled by configuration"
            )

    def _get_factory(self, resource_name: ResourceName) -> ResourceFactory:
        override = getattr(self.factories, resource_name.value)
        if override is not None:
            return override

        return {
            ResourceName.CHAT_MODEL: _build_chat_model,
            ResourceName.EMBEDDING: _build_embedding,
            ResourceName.CHROMA: _build_chroma,
            ResourceName.BM25: _build_bm25,
            ResourceName.NEO4J: _build_neo4j,
        }[resource_name]

    @staticmethod
    def _close_resource(resource: Any) -> None:
        for method_name in ("close", "shutdown", "dispose"):
            method = getattr(resource, method_name, None)
            if callable(method):
                method()
                return


def _required_secret(value: Any, field_name: str) -> str:
    if value is None:
        raise ConfigurationError(f"Missing required setting: {field_name}")
    secret = value.get_secret_value().strip()
    if not secret:
        raise ConfigurationError(f"Missing required setting: {field_name}")
    return secret


def _existing_directory(settings: Settings, path: Path, field_name: str) -> Path:
    resolved = settings.resolve_project_path(path)
    if not resolved.is_dir():
        raise ConfigurationError(f"{field_name} directory does not exist: {resolved}")
    return resolved


def _build_chat_model(container: ResourceContainer) -> Any:
    from langchain_openai import ChatOpenAI

    settings = container.settings
    return ChatOpenAI(
        model=settings.chat_model,
        api_key=_required_secret(settings.chat_api_key, "CHAT_API_KEY"),
        base_url=settings.chat_base_url,
        temperature=settings.chat_temperature,
        timeout=settings.chat_timeout_seconds,
        max_retries=settings.chat_max_retries,
    )


def _build_embedding(container: ResourceContainer) -> Any:
    from langchain_huggingface import HuggingFaceEmbeddings

    settings = container.settings
    model_path = _existing_directory(
        settings,
        settings.embedding_model_path,
        "EMBEDDING_MODEL_PATH",
    )
    return HuggingFaceEmbeddings(
        model_name=str(model_path),
        model_kwargs={
            "device": settings.embedding_device,
            "local_files_only": settings.embedding_offline,
        },
        encode_kwargs={"normalize_embeddings": True},
    )


def _build_chroma(container: ResourceContainer) -> Any:
    from langchain_chroma import Chroma

    settings = container.settings
    persist_dir = settings.resolve_project_path(settings.chroma_persist_dir)
    persist_dir.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=settings.chroma_collection_name,
        embedding_function=container.get_embedding(),
        persist_directory=str(persist_dir),
    )


def _build_bm25(container: ResourceContainer) -> Any:
    del container
    from rag.retrieval.bm25_retriever import BM25RecipeRetriever

    return BM25RecipeRetriever()


def _build_neo4j(container: ResourceContainer) -> Any:
    from neo4j import GraphDatabase

    settings = container.settings
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(
            settings.neo4j_username,
            _required_secret(settings.neo4j_password, "NEO4J_PASSWORD"),
        ),
        connection_timeout=settings.neo4j_connect_timeout_seconds,
    )
    driver.verify_connectivity()
    return driver
