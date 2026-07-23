from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NORMAL_RUNTIME_FILES = (
    PROJECT_ROOT / "recipe_assistant" / "api" / "dependencies.py",
    PROJECT_ROOT / "recipe_assistant" / "agents" / "factory.py",
    PROJECT_ROOT / "recipe_assistant" / "main.py",
    PROJECT_ROOT / "recipe_assistant" / "services" / "chat.py",
    PROJECT_ROOT / "frontend" / "streamlit_app.py",
)
FORBIDDEN_MODULES = {
    "agent",
    "agent.react_agent",
    "recipe_assistant.agents.harness",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_normal_runtime_has_no_legacy_imports_or_dynamic_loader() -> None:
    for path in NORMAL_RUNTIME_FILES:
        imports = _imports(path)
        assert not {
            module
            for module in imports
            if module in FORBIDDEN_MODULES or module.startswith("agent.")
        }, path

        source = path.read_text(encoding="utf-8")
        assert "LegacyReactAgentAdapter" not in source
        assert "LazyLegacyExecutor" not in source
        assert "__import__(\"agent" not in source
        assert "import_module(\"agent" not in source


def test_frontend_remains_api_only() -> None:
    source = (PROJECT_ROOT / "frontend" / "streamlit_app.py").read_text(
        encoding="utf-8"
    )
    assert "/api/chat/stream" in source
    assert "recipe_assistant." not in source
    assert "agent." not in source
