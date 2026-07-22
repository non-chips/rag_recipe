from __future__ import annotations

import pytest

from rag.ingestion.metadata_normalizer import (
    MissingRecipeIdError,
    MissingRecipeIdPolicy,
    normalize_metadata,
)


def test_normalizer_preserves_legacy_keys_and_adds_canonical_fields() -> None:
    result = normalize_metadata(
        {
            "node_id": "recipe_legacy",
            "source": "data/recipes/宫保鸡丁.md",
            "file_md5": "abc123",
            "parent_id": "parent_0",
            "parent_index": 0,
            "child_index": 2,
            "custom_field": "keep-me",
        }
    )

    assert result.metadata is not None
    assert result.metadata["recipe_id"] == "recipe_legacy"
    assert result.metadata["recipe_name"] == "宫保鸡丁"
    assert result.metadata["source_path"] == "data/recipes/宫保鸡丁.md"
    assert result.metadata["chunk_id"] == "recipe_legacy:parent:0:child:2"
    assert result.metadata["schema_version"] == "retrieval_metadata_v1"
    assert result.metadata["knowledge_version"] == "md5:abc123"
    assert result.metadata["node_id"] == "recipe_legacy"
    assert result.metadata["source"] == "data/recipes/宫保鸡丁.md"
    assert result.metadata["custom_field"] == "keep-me"
    assert len(result.warnings) == 2


def test_normalizer_prefers_canonical_values() -> None:
    result = normalize_metadata(
        {
            "recipe_id": "recipe_new",
            "node_id": "recipe_old",
            "recipe_name": "鱼香肉丝",
            "source_path": "canonical.md",
            "source": "legacy.md",
            "schema_version": "schema_v2",
            "knowledge_version": "knowledge_2026_07",
            "ingredients": ["猪肉", " 猪肉 ", "木耳"],
            "tools": "炒锅",
        }
    )

    assert result.metadata is not None
    assert result.metadata["recipe_id"] == "recipe_new"
    assert result.metadata["source_path"] == "canonical.md"
    assert result.metadata["schema_version"] == "schema_v2"
    assert result.metadata["knowledge_version"] == "knowledge_2026_07"
    assert result.metadata["ingredients"] == ["猪肉", "木耳"]
    assert result.metadata["tools"] == ["炒锅"]
    assert result.warnings == ()


def test_missing_recipe_id_raises_by_default() -> None:
    with pytest.raises(MissingRecipeIdError, match="recipe_id.*node_id"):
        normalize_metadata({"source": "data/unknown.md"})


def test_missing_recipe_id_can_be_explicitly_skipped() -> None:
    result = normalize_metadata(
        {"source": "data/unknown.md"},
        missing_recipe_id=MissingRecipeIdPolicy.SKIP,
    )

    assert result.skipped is True
    assert result.metadata is None
    assert result.warnings == (
        "metadata is missing a non-empty recipe_id and legacy node_id",
    )
