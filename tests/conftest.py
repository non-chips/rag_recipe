from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))


@pytest.fixture
def fresh_import() -> Iterator[Callable[[str], ModuleType]]:
    """Import a production module after test doubles are installed."""

    imported_modules: list[str] = []

    def _import(module_name: str) -> ModuleType:
        sys.modules.pop(module_name, None)
        importlib.invalidate_caches()
        module = importlib.import_module(module_name)
        imported_modules.append(module_name)
        return module

    yield _import

    for module_name in imported_modules:
        sys.modules.pop(module_name, None)
