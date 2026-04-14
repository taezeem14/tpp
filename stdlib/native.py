from __future__ import annotations

import json
import math
import os
import time as pytime
from pathlib import Path
from typing import Any, Callable

from tpp.core.errors import SecurityTppError


class NativeModule:
    def __init__(self, name: str, members: dict[str, Any]) -> None:
        self.__name = name
        self.__members = members

    @property
    def name(self) -> str:
        return self.__name

    def has_member(self, key: str) -> bool:
        return key in self.__members

    def member(self, key: str) -> Any:
        return self.__members[key]

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__members)

    def __getattr__(self, item: str) -> Any:
        if item in self.__members:
            return self.__members[item]
        raise AttributeError(f"{self.__name} has no attribute {item}")

    def __repr__(self) -> str:
        return f"<NativeModule {self.__name}>"


def _safe_divide(a: float, b: float) -> float:
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b


def _safe_sleep(seconds: float) -> None:
    if seconds < 0:
        raise ValueError("Sleep duration must be non-negative")
    if seconds > 30:
        raise ValueError("Sleep duration is capped at 30 seconds for safety")
    pytime.sleep(seconds)


def _resolve_path(base_dir: Path, raw_path: str) -> Path:
    requested = Path(raw_path)
    resolved = (base_dir / requested).resolve() if not requested.is_absolute() else requested.resolve()

    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError as exc:
        raise SecurityTppError("System module cannot access paths outside workspace.") from exc
    return resolved


def build_math_module() -> NativeModule:
    return NativeModule(
        "math",
        {
            "add": lambda a, b: a + b,
            "subtract": lambda a, b: a - b,
            "multiply": lambda a, b: a * b,
            "divide": _safe_divide,
            "power": lambda a, b: a**b,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "floor": math.floor,
            "ceil": math.ceil,
            "pi": math.pi,
            "e": math.e,
        },
    )


def build_text_module() -> NativeModule:
    return NativeModule(
        "text",
        {
            "upper": lambda s: str(s).upper(),
            "lower": lambda s: str(s).lower(),
            "title": lambda s: str(s).title(),
            "strip": lambda s: str(s).strip(),
            "replace": lambda s, old, new: str(s).replace(str(old), str(new)),
            "contains": lambda s, needle: str(needle) in str(s),
            "split": lambda s, sep=None: str(s).split(sep),
            "join": lambda sep, items: str(sep).join(str(item) for item in items),
            "format": lambda template, *args, **kwargs: str(template).format(*args, **kwargs),
            "length": lambda s: len(str(s)),
        },
    )


def build_system_module(base_dir: Path) -> NativeModule:
    def read_text(path: str, encoding: str = "utf-8") -> str:
        resolved = _resolve_path(base_dir, path)
        return resolved.read_text(encoding=encoding)

    def write_text(path: str, content: str, encoding: str = "utf-8") -> str:
        resolved = _resolve_path(base_dir, path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(str(content), encoding=encoding)
        return str(resolved)

    def list_dir(path: str = ".") -> list[str]:
        resolved = _resolve_path(base_dir, path)
        return sorted(entry.name + ("/" if entry.is_dir() else "") for entry in resolved.iterdir())

    def read_json(path: str, encoding: str = "utf-8") -> Any:
        return json.loads(read_text(path, encoding))

    def write_json(path: str, payload: Any, encoding: str = "utf-8") -> str:
        return write_text(path, json.dumps(payload, indent=2), encoding)

    return NativeModule(
        "system",
        {
            "cwd": lambda: str(base_dir.resolve()),
            "exists": lambda path: _resolve_path(base_dir, path).exists(),
            "read_text": read_text,
            "write_text": write_text,
            "list_dir": list_dir,
            "read_json": read_json,
            "write_json": write_json,
            "get_env": lambda key, default=None: os.environ.get(str(key), default),
        },
    )


def build_time_module() -> NativeModule:
    return NativeModule(
        "time",
        {
            "now": lambda: pytime.time(),
            "timestamp": lambda: pytime.time(),
            "millis": lambda: int(pytime.time() * 1000),
            "sleep": _safe_sleep,
            "iso_now": lambda: __import__("datetime").datetime.datetime.utcnow().isoformat() + "Z",
        },
    )


def create_native_stdlib_registry(base_dir: Path) -> dict[str, NativeModule]:
    return {
        "math": build_math_module(),
        "text": build_text_module(),
        "system": build_system_module(base_dir),
        "time": build_time_module(),
    }
