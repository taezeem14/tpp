from __future__ import annotations

import importlib
from typing import Any

from tpp.core.constants import ALLOWED_PYTHON_MODULES
from tpp.core.errors import RuntimeTppError, SecurityTppError


class SafePythonInterop:
    """Controlled Python bridge used by runtime imports and optional calls."""

    def __init__(self) -> None:
        self.allowed_modules = set(ALLOWED_PYTHON_MODULES)

    def import_module(self, module_name: str, line: int) -> Any:
        root = module_name.split(".")[0]
        if root not in self.allowed_modules:
            raise SecurityTppError(f"Module '{module_name}' is not allowed.", line)
        try:
            return importlib.import_module(module_name)
        except Exception as exc:
            raise RuntimeTppError(f"Could not import module '{module_name}'.", line) from exc

    def import_from(self, module_name: str, member_name: str, line: int) -> Any:
        module = self.import_module(module_name, line)
        if not hasattr(module, member_name):
            raise RuntimeTppError(f"'{module_name}' has no member named '{member_name}'.", line)
        return getattr(module, member_name)

    def validate_callable(self, target: Any, line: int) -> None:
        if callable(target):
            return
        raise RuntimeTppError("That value is not callable.", line)
