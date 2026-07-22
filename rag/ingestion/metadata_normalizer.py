"""Convert legacy recipe document metadata to the retrieval contract."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping

from recipe_assistant.schemas.retrieval import (
    RETRIEVAL_METADATA_SCHEMA_VERSION,
    UNVERSIONED_KNOWLEDGE,
    NormalizedRetrievalMetadata,
)


class MissingRecipeIdPolicy(str, Enum):
    """Supported behavior when metadata has no stable recipe identity."""

    ERROR = "error"
    SKIP = "skip"


class MissingRecipeIdError(ValueError):
    """Raised when neither recipe_id nor its legacy node_id alias is present."""


@dataclass(frozen=True, slots=True)
class MetadataNormalizationResult:
    """Outcome of one metadata conversion."""

    metadata: dict[str, Any] | None
    warnings: tuple[str, ...] = ()
    skipped: bool = False


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _first_text(metadata: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _clean_text(metadata.get(key))
        if value is not None:
            return value
    return None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return list(
        dict.fromkeys(cleaned for item in values if (cleaned := _clean_text(item)) is not None)
    )


def _name_from_source(source_path: str | None) -> str | None:
    if not source_path:
        return None
    return PurePosixPath(source_path.replace("\\", "/")).stem or None


def normalize_metadata(
    metadata: Mapping[str, Any],
    *,
    missing_recipe_id: MissingRecipeIdPolicy = MissingRecipeIdPolicy.ERROR,
) -> MetadataNormalizationResult:
    """Add canonical fields without removing legacy metadata keys.

    ``recipe_id`` is authoritative. A non-empty legacy ``node_id`` is accepted
    as the same stable identity. No identity is synthesized from content or a
    process-local hash.
    """

    policy = MissingRecipeIdPolicy(missing_recipe_id)
    warnings: list[str] = []
    recipe_id = _first_text(metadata, "recipe_id")
    if recipe_id is None:
        recipe_id = _first_text(metadata, "node_id")
        if recipe_id is not None:
            warnings.append("recipe_id populated from legacy node_id")

    if recipe_id is None:
        message = "metadata is missing a non-empty recipe_id and legacy node_id"
        if policy is MissingRecipeIdPolicy.SKIP:
            return MetadataNormalizationResult(
                metadata=None,
                warnings=(message,),
                skipped=True,
            )
        raise MissingRecipeIdError(message)

    source_path = _first_text(metadata, "source_path", "source", "file_path") or ""
    recipe_name = _first_text(metadata, "recipe_name", "name", "title")
    if recipe_name is None:
        recipe_name = _name_from_source(source_path)

    parent_id = _first_text(metadata, "parent_id")
    chunk_id = _first_text(metadata, "chunk_id")
    if chunk_id is None and metadata.get("child_index") is not None:
        parent_index = metadata.get("parent_index", 0)
        chunk_id = f"{recipe_id}:parent:{parent_index}:child:{metadata['child_index']}"
        warnings.append("chunk_id derived from legacy parent_index/child_index")

    knowledge_version = _first_text(metadata, "knowledge_version")
    if knowledge_version is None:
        file_md5 = _first_text(metadata, "file_md5")
        knowledge_version = f"md5:{file_md5}" if file_md5 else UNVERSIONED_KNOWLEDGE

    canonical = NormalizedRetrievalMetadata(
        recipe_id=recipe_id,
        recipe_name=recipe_name,
        source_path=source_path,
        parent_id=parent_id,
        chunk_id=chunk_id,
        schema_version=(
            _first_text(metadata, "schema_version", "chunk_schema_version")
            or RETRIEVAL_METADATA_SCHEMA_VERSION
        ),
        knowledge_version=knowledge_version,
        category=_first_text(metadata, "category"),
        ingredients=_string_list(metadata.get("ingredients")),
        tools=_string_list(metadata.get("tools")),
    )

    normalized = dict(metadata)
    normalized.update(canonical.model_dump())
    return MetadataNormalizationResult(
        metadata=normalized,
        warnings=tuple(warnings),
        skipped=False,
    )
