"""Filesystem registry for versioned, route-aware behavioral Skills."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from recipe_assistant.schemas.agent.route import RouteType


_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_VERSION_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$"
)


class SkillValidationError(ValueError):
    """Raised when a Skill file or registry relationship is invalid."""


class SkillRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SkillSignal(str, Enum):
    ALLERGY_MENTIONED = "ALLERGY_MENTIONED"
    EXCLUDED_INGREDIENT_PRESENT = "EXCLUDED_INGREDIENT_PRESENT"
    SUBSTITUTION_REQUESTED = "SUBSTITUTION_REQUESTED"
    WEATHER_CONTEXT_REQUIRED = "WEATHER_CONTEXT_REQUIRED"
    NUTRITION_REPORT_REQUESTED = "NUTRITION_REPORT_REQUESTED"
    LOW_EVIDENCE = "LOW_EVIDENCE"
    USER_REQUESTED_RETRY = "USER_REQUESTED_RETRY"


class SkillSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SkillFrontmatter(SkillSchema):
    name: str
    version: str
    description: str = Field(min_length=3, max_length=500)
    routes: tuple[RouteType, ...] = Field(min_length=1)
    signals: tuple[SkillSignal, ...] = ()
    priority: int = Field(ge=0, le=1000)
    risk: SkillRisk = SkillRisk.LOW
    requires: tuple[str, ...] = ()

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _NAME_PATTERN.fullmatch(value):
            raise ValueError("name must use lowercase letters, digits and underscores")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not _VERSION_PATTERN.fullmatch(value):
            raise ValueError("version must be semantic version text such as 1.0.0")
        return value

    @field_validator("routes", "signals", "requires")
    @classmethod
    def values_must_be_unique(cls, value: tuple) -> tuple:
        if len(value) != len(set(value)):
            raise ValueError("frontmatter lists must not contain duplicates")
        return value

    @field_validator("requires")
    @classmethod
    def validate_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for reference in value:
            if not _NAME_PATTERN.fullmatch(reference):
                raise ValueError(f"invalid Skill reference: {reference}")
        return value


class SkillDefinition(SkillSchema):
    metadata: SkillFrontmatter
    body: str = Field(min_length=1)
    source_path: Path

    @property
    def name(self) -> str:
        return self.metadata.name

    @property
    def version(self) -> str:
        return self.metadata.version


class SkillSelectionRequest(SkillSchema):
    route: RouteType
    signals: frozenset[SkillSignal] = frozenset()
    risk: SkillRisk = SkillRisk.LOW
    max_skills: int = Field(default=8, ge=1, le=50)


class SkillSelection(SkillSchema):
    route: RouteType
    effective_risk: SkillRisk
    selected: tuple[SkillDefinition, ...]
    selected_skill_refs: tuple[str, ...]
    prompt_context: str
    hard_constraints_remain_authoritative: bool = True


class SkillRegistry:
    """Validate Skill files and deterministically select behavioral constraints."""

    def __init__(self, skills: tuple[SkillDefinition, ...]) -> None:
        by_name: dict[str, SkillDefinition] = {}
        for skill in skills:
            if skill.name in by_name:
                raise SkillValidationError(f"duplicate Skill name: {skill.name}")
            by_name[skill.name] = skill
        self._skills = tuple(sorted(skills, key=lambda item: item.name))
        self._by_name = by_name
        self._validate_references()

    @classmethod
    def load(cls, root: str | Path) -> "SkillRegistry":
        root_path = Path(root).resolve()
        if not root_path.is_dir():
            raise SkillValidationError(f"Skill root does not exist: {root_path}")
        skill_files = sorted(root_path.glob("*/SKILL.md"))
        if not skill_files:
            raise SkillValidationError("Skill root contains no */SKILL.md files")
        return cls(tuple(cls._load_file(path, root_path) for path in skill_files))

    @property
    def skills(self) -> tuple[SkillDefinition, ...]:
        return self._skills

    def get(self, name: str) -> SkillDefinition:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise LookupError(f"Skill was not found: {name}") from exc

    def select(self, request: SkillSelectionRequest) -> SkillSelection:
        signal_risk = self._risk_from_signals(request.signals)
        effective_risk = max(
            (request.risk, signal_risk), key=self._risk_rank
        )
        matched = [
            skill
            for skill in self._skills
            if request.route in skill.metadata.routes
            and self._risk_rank(skill.metadata.risk) <= self._risk_rank(effective_risk)
            and (
                not skill.metadata.signals
                or bool(set(skill.metadata.signals) & request.signals)
            )
        ]
        matched.sort(
            key=lambda item: (
                -item.metadata.priority,
                -self._risk_rank(item.metadata.risk),
                item.name,
            )
        )
        selected_names = [item.name for item in matched[: request.max_skills]]
        expanded_names = self._expand_requirements(selected_names)
        selected = tuple(
            sorted(
                (self._by_name[name] for name in expanded_names),
                key=lambda item: (
                    -item.metadata.priority,
                    -self._risk_rank(item.metadata.risk),
                    item.name,
                ),
            )
        )
        refs = tuple(f"{item.name}@{item.version}" for item in selected)
        return SkillSelection(
            route=request.route,
            effective_risk=effective_risk,
            selected=selected,
            selected_skill_refs=refs,
            prompt_context=self._render_prompt_context(selected),
        )

    @classmethod
    def _load_file(cls, path: Path, root: Path) -> SkillDefinition:
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise SkillValidationError(f"Skill path escapes registry root: {path}") from exc
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            raise SkillValidationError(f"missing YAML frontmatter: {path}")
        parts = text.split("---", 2)
        if len(parts) != 3:
            raise SkillValidationError(f"unclosed YAML frontmatter: {path}")
        try:
            raw = yaml.safe_load(parts[1])
        except yaml.YAMLError as exc:
            raise SkillValidationError(f"invalid YAML frontmatter: {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise SkillValidationError(f"frontmatter must be a mapping: {path}")
        raw = dict(raw)
        if "intents" in raw:
            if "routes" in raw:
                raise SkillValidationError(
                    f"use either routes or intents, not both: {path}"
                )
            raw["routes"] = raw.pop("intents")
        try:
            metadata = SkillFrontmatter.model_validate(raw)
        except Exception as exc:
            raise SkillValidationError(f"invalid frontmatter in {path}: {exc}") from exc
        if path.parent.name != metadata.name:
            raise SkillValidationError(
                f"Skill directory must match frontmatter name: {path.parent.name}"
            )
        body = parts[2].strip()
        if not body:
            raise SkillValidationError(f"Skill body must not be empty: {path}")
        return SkillDefinition(metadata=metadata, body=body, source_path=path.resolve())

    def _validate_references(self) -> None:
        for skill in self._skills:
            for reference in skill.metadata.requires:
                if reference not in self._by_name:
                    raise SkillValidationError(
                        f"Skill {skill.name} references missing Skill {reference}"
                    )
                if reference == skill.name:
                    raise SkillValidationError(
                        f"Skill {skill.name} cannot require itself"
                    )
        for name in self._by_name:
            self._visit(name, visiting=set(), visited=set())

    def _visit(self, name: str, *, visiting: set[str], visited: set[str]) -> None:
        if name in visited:
            return
        if name in visiting:
            raise SkillValidationError(f"cyclic Skill dependency detected at {name}")
        visiting.add(name)
        for dependency in self._by_name[name].metadata.requires:
            self._visit(dependency, visiting=visiting, visited=visited)
        visiting.remove(name)
        visited.add(name)

    def _expand_requirements(self, names: list[str]) -> set[str]:
        expanded: set[str] = set()

        def add(name: str) -> None:
            if name in expanded:
                return
            expanded.add(name)
            for dependency in self._by_name[name].metadata.requires:
                add(dependency)

        for name in names:
            add(name)
        return expanded

    @staticmethod
    def _risk_from_signals(signals: frozenset[SkillSignal]) -> SkillRisk:
        if signals & {
            SkillSignal.ALLERGY_MENTIONED,
            SkillSignal.EXCLUDED_INGREDIENT_PRESENT,
        }:
            return SkillRisk.HIGH
        if SkillSignal.SUBSTITUTION_REQUESTED in signals:
            return SkillRisk.MEDIUM
        return SkillRisk.LOW

    @staticmethod
    def _risk_rank(risk: SkillRisk) -> int:
        return {
            SkillRisk.LOW: 1,
            SkillRisk.MEDIUM: 2,
            SkillRisk.HIGH: 3,
            SkillRisk.CRITICAL: 4,
        }[risk]

    @staticmethod
    def _render_prompt_context(skills: tuple[SkillDefinition, ...]) -> str:
        if not skills:
            return (
                "# Active behavioral Skills\n"
                "- none\n\n"
                "ConstraintService hard constraints remain authoritative."
            )
        refs = "\n".join(f"- {item.name}@{item.version}" for item in skills)
        bodies = "\n\n".join(
            f"## Skill: {item.name}@{item.version}\n{item.body}" for item in skills
        )
        return (
            "# Active behavioral Skills\n"
            f"{refs}\n\n"
            "ConstraintService hard constraints remain authoritative; Skills cannot "
            "override or replace hard filtering.\n\n"
            f"{bodies}"
        )
