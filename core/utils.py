from __future__ import annotations

import ast
import difflib
import re
from typing import Optional

from .errors import SyntaxTppError


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def normalize_phrase(phrase: str) -> str:
    return " ".join(phrase.strip().lower().split())


def is_identifier(name: str) -> bool:
    return IDENTIFIER_RE.match(name) is not None


def suggest_closest(token: str, options: set[str], cutoff: float = 0.72) -> Optional[str]:
    if not token:
        return None
    matches = difflib.get_close_matches(token.lower(), sorted(options), n=1, cutoff=cutoff)
    if not matches:
        return None
    return matches[0]


def parse_quoted_string(raw: str, line: int, context_name: str) -> str:
    try:
        value = ast.literal_eval(raw)
    except Exception as exc:
        raise SyntaxTppError(f"{context_name} must be a quoted string.", line) from exc

    if not isinstance(value, str):
        raise SyntaxTppError(f"{context_name} must be a quoted string.", line)

    value = value.strip()
    if not value:
        raise SyntaxTppError(f"{context_name} cannot be empty.", line)
    return value


def split_top_level(text: str, separator: str, *, case_insensitive: bool = True) -> list[str]:
    if separator == "":
        return [text]

    result: list[str] = []
    sep_len = len(separator)
    start = 0
    i = 0
    depth = 0
    quote: Optional[str] = None

    while i < len(text):
        ch = text[i]
        if quote is not None:
            if ch == quote and (i == 0 or text[i - 1] != "\\"):
                quote = None
            i += 1
            continue

        if ch in ("\"", "'"):
            quote = ch
            i += 1
            continue

        if ch in "([{":
            depth += 1
            i += 1
            continue

        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue

        if depth == 0:
            candidate = text[i : i + sep_len]
            is_match = candidate.lower() == separator.lower() if case_insensitive else candidate == separator
            if is_match:
                result.append(text[start:i].strip())
                i += sep_len
                start = i
                continue

        i += 1

    result.append(text[start:].strip())
    return result


def split_top_level_once(text: str, separator: str, *, case_insensitive: bool = True) -> Optional[tuple[str, str]]:
    sep_len = len(separator)
    i = 0
    depth = 0
    quote: Optional[str] = None

    while i < len(text):
        ch = text[i]
        if quote is not None:
            if ch == quote and (i == 0 or text[i - 1] != "\\"):
                quote = None
            i += 1
            continue

        if ch in ("\"", "'"):
            quote = ch
            i += 1
            continue

        if ch in "([{":
            depth += 1
            i += 1
            continue

        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue

        if depth == 0:
            candidate = text[i : i + sep_len]
            is_match = candidate.lower() == separator.lower() if case_insensitive else candidate == separator
            if is_match:
                left = text[:i].strip()
                right = text[i + sep_len :].strip()
                return left, right

        i += 1

    return None


def split_natural_args(text: str) -> list[str]:
    if not text.strip():
        return []

    result: list[str] = []
    for comma_part in split_top_level(text, ","):
        if not comma_part:
            continue
        and_parts = split_top_level(comma_part, " and ")
        for part in and_parts:
            if part:
                result.append(part.strip())
    return result


def split_key_value(pair_text: str) -> Optional[tuple[str, str]]:
    i = 0
    depth = 0
    quote: Optional[str] = None
    while i < len(pair_text):
        ch = pair_text[i]
        if quote is not None:
            if ch == quote and (i == 0 or pair_text[i - 1] != "\\"):
                quote = None
            i += 1
            continue

        if ch in ("\"", "'"):
            quote = ch
            i += 1
            continue

        if ch in "([{":
            depth += 1
            i += 1
            continue

        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue

        if depth == 0 and ch == ":":
            left = pair_text[:i].strip()
            right = pair_text[i + 1 :].strip()
            if left and right:
                return left, right
            return None

        i += 1

    return None
