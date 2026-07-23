from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_v2_container_startup_does_not_load_or_register_legacy(tmp_path: Path) -> None:
    script = """
import sys
from recipe_assistant.api.dependencies import ApiContainer
from recipe_assistant.core.config import Settings

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
container = ApiContainer.build_default(settings)
container.startup()
try:
    assert container.chat_runner.harness.mode == "v2"
    assert "agent" not in sys.modules
    assert "agent.react_agent" not in sys.modules
    assert "recipe_assistant.agents.harness" not in sys.modules
    assert not hasattr(container.chat_runner.harness, "legacy_executor")
    assert not hasattr(container.chat_runner.harness, "shadow_sink")
finally:
    container.shutdown()
"""
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{(tmp_path / 'startup.db').as_posix()}"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
