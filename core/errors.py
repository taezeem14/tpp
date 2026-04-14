from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DiagnosticHint:
    suggestion: Optional[str] = None
    fix_preview: Optional[str] = None


class TppError(Exception):
    """Base class for all language errors."""

    category: str = "general"

    def __init__(
        self,
        message: str,
        line: Optional[int] = None,
        *,
        suggestion: Optional[str] = None,
        fix_preview: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.line = line
        self.suggestion = suggestion
        self.fix_preview = fix_preview

    def __str__(self) -> str:
        prefix = f"Line {self.line}: " if self.line is not None else ""
        parts = [f"{prefix}{self.message}"]
        if self.suggestion:
            parts.append(f"Hint: {self.suggestion}")
        if self.fix_preview:
            parts.append(f"Try: {self.fix_preview}")
        return "\n".join(parts)


class SyntaxTppError(TppError):
    category = "syntax"


class SemanticTppError(TppError):
    category = "semantic"


class RuntimeTppError(TppError):
    category = "runtime"


class PluginTppError(TppError):
    category = "plugin"


class SecurityTppError(TppError):
    category = "security"


class IncompleteBlockError(SyntaxTppError):
    pass


class ReturnSignal(Exception):
    def __init__(self, value: object) -> None:
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


def render_error(exc: Exception, *, debug_trace: bool = False) -> str:
    if isinstance(exc, TppError):
        return str(exc)
    if debug_trace:
        import traceback

        return "".join(traceback.format_exception(exc))
    return str(exc)
