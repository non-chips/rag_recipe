from __future__ import annotations

from collections import Counter

import pytest

from recipe_assistant.core.config import Settings
from recipe_assistant.core.container import (
    ResourceContainer,
    ResourceFactories,
    ResourceName,
)
from recipe_assistant.core.exceptions import ResourceDisabledError


class ClosableResource:
    def __init__(self, name: str) -> None:
        self.name = name
        self.close_count = 0

    def close(self) -> None:
        self.close_count += 1


def _counting_factories(counter: Counter) -> ResourceFactories:
    def factory(name: str):
        def build(container: ResourceContainer) -> ClosableResource:
            assert isinstance(container.settings, Settings)
            counter[name] += 1
            return ClosableResource(name)

        return build

    return ResourceFactories(
        chat_model=factory("chat_model"),
        embedding=factory("embedding"),
        chroma=factory("chroma"),
        bm25=factory("bm25"),
        neo4j=factory("neo4j"),
    )


def test_embedding_and_bm25_are_built_once_per_container() -> None:
    counter = Counter()
    container = ResourceContainer(
        Settings(_env_file=None),
        _counting_factories(counter),
    )

    assert container.get_embedding() is container.get_embedding()
    assert container.get_bm25() is container.get_bm25()
    assert counter == Counter({"embedding": 1, "bm25": 1})


def test_all_long_lived_resources_are_lazy_singletons() -> None:
    counter = Counter()
    settings = Settings(_env_file=None, neo4j_enabled=True)
    container = ResourceContainer(settings, _counting_factories(counter))

    getters = {
        "chat_model": container.get_chat_model,
        "embedding": container.get_embedding,
        "chroma": container.get_chroma,
        "bm25": container.get_bm25,
        "neo4j": container.get_neo4j,
    }
    for name, getter in getters.items():
        assert getter() is getter()
        assert counter[name] == 1


def test_startup_prewarms_selected_resources_and_shutdown_is_idempotent() -> None:
    counter = Counter()
    container = ResourceContainer(
        Settings(_env_file=None),
        _counting_factories(counter),
    )

    container.startup([ResourceName.EMBEDDING, ResourceName.BM25])
    embedding = container.get_embedding()
    bm25 = container.get_bm25()

    assert container.started is True
    assert counter == Counter({"embedding": 1, "bm25": 1})

    container.shutdown()
    container.shutdown()

    assert container.started is False
    assert embedding.close_count == 1
    assert bm25.close_count == 1


def test_disabled_neo4j_is_not_constructed() -> None:
    counter = Counter()
    container = ResourceContainer(
        Settings(_env_file=None, neo4j_enabled=False),
        _counting_factories(counter),
    )

    with pytest.raises(ResourceDisabledError, match="neo4j"):
        container.get_neo4j()

    assert counter["neo4j"] == 0
