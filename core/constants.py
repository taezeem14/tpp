from __future__ import annotations

ALLOWED_PYTHON_MODULES = {
    "math",
    "random",
    "datetime",
    "os",
    "json",
    "time",
    "statistics",
    "functools",
    "itertools",
}

NATIVE_STDLIB_MODULES = {
    "math",
    "text",
    "system",
    "time",
}

SAFE_GLOBAL_NAMES = {
    "True": True,
    "False": False,
    "None": None,
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "round": round,
    "sorted": sorted,
    "range": range,
}

CORE_STATEMENT_STARTERS = {
    "bring",
    "say",
    "ask",
    "let",
    "change",
    "if",
    "but",
    "otherwise",
    "keep",
    "for",
    "repeat",
    "count",
    "stop",
    "skip",
    "do",
    "define",
    "give",
    "add",
    "remove",
    "set",
    "create",
    "when",
    "remember",
    "call",
    "run",
    "test",
    "suite",
    "expect",
    "register",
    "describe",
    "increase",
    "decrease",
    "make",
    "on",
    "show",
}

PARSER_MODES = {"strict", "fuzzy", "intent"}

DEFAULT_REWRITE_LIMIT = 8
