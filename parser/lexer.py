from __future__ import annotations

import re
from dataclasses import dataclass

from tpp.core.ast_nodes import Token
from tpp.core.errors import RuntimeTppError


@dataclass
class LexerStats:
    cache_hits: int = 0
    cache_misses: int = 0


class ExpressionTokenizer:
    """Tokenizer that understands multi-word English operators."""

    PHRASE_OPS: list[tuple[tuple[str, ...], str]] = [
        (("to", "the", "power", "of"), "**"),
        (("divided", "by"), "/"),
        (("is", "greater", "than", "or", "equal", "to"), ">="),
        (("is", "less", "than", "or", "equal", "to"), "<="),
        (("is", "greater", "than"), ">"),
        (("is", "less", "than"), "<"),
        (("is", "at", "least"), ">="),
        (("is", "at", "most"), "<="),
        (("is", "not", "equal", "to"), "!="),
        (("is", "equal", "to"), "=="),
        (("is", "not", "in"), "not in"),
        (("is", "in"), "in"),
        (("greater", "than", "or", "equal", "to"), ">="),
        (("less", "than", "or", "equal", "to"), "<="),
        (("greater", "than"), ">"),
        (("less", "than"), "<"),
        (("not", "equal", "to"), "!="),
        (("equal", "to"), "=="),
        (("at", "least"), ">="),
        (("at", "most"), "<="),
    ]

    WORD_OPS = {
        "plus": "+",
        "minus": "-",
        "times": "*",
        "modulo": "%",
        "and": "and",
        "or": "or",
        "not": "not",
        "in": "in",
        "is": "==",
    }

    SYMBOLS = set("()[]{}.,:")

    def __init__(self) -> None:
        self._sorted_phrases = sorted(self.PHRASE_OPS, key=lambda pair: len(pair[0]), reverse=True)
        self._python_expr_cache: dict[str, str] = {}
        self.stats = LexerStats()

    def clear_cache(self) -> None:
        self._python_expr_cache.clear()
        self.stats = LexerStats()

    def tokenize(self, text: str, line: int) -> list[Token]:
        raw: list[Token] = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch.isspace():
                i += 1
                continue
            if ch in ("\"", "'"):
                start = i
                quote = ch
                i += 1
                escaped = False
                while i < len(text):
                    curr = text[i]
                    if curr == quote and not escaped:
                        i += 1
                        break
                    escaped = curr == "\\" and not escaped
                    if curr != "\\":
                        escaped = False
                    i += 1
                else:
                    raise RuntimeTppError("Unterminated string literal.", line)
                raw.append(Token("string", text[start:i], line, start + 1))
                continue
            if ch.isdigit():
                start = i
                has_dot = False
                while i < len(text) and (text[i].isdigit() or (text[i] == "." and not has_dot)):
                    if text[i] == ".":
                        has_dot = True
                    i += 1
                raw.append(Token("number", text[start:i], line, start + 1))
                continue
            if ch.isalpha() or ch == "_":
                start = i
                while i < len(text) and (text[i].isalnum() or text[i] == "_"):
                    i += 1
                raw.append(Token("word", text[start:i], line, start + 1))
                continue
            if text.startswith("**", i):
                raw.append(Token("op", "**", line, i + 1))
                i += 2
                continue
            if text.startswith(">=", i) or text.startswith("<=", i) or text.startswith("!=", i) or text.startswith("==", i):
                raw.append(Token("op", text[i : i + 2], line, i + 1))
                i += 2
                continue
            if ch in "+-*/%><":
                raw.append(Token("op", ch, line, i + 1))
                i += 1
                continue
            if ch in self.SYMBOLS:
                raw.append(Token("symbol", ch, line, i + 1))
                i += 1
                continue
            raise RuntimeTppError(f"Unexpected character '{ch}' in expression.", line)

        return self._merge_multi_word_tokens(raw)

    def _merge_multi_word_tokens(self, raw: list[Token]) -> list[Token]:
        merged: list[Token] = []
        i = 0
        while i < len(raw):
            token = raw[i]
            if token.kind != "word":
                merged.append(token)
                i += 1
                continue

            matched = False
            for phrase_words, replacement in self._sorted_phrases:
                end = i + len(phrase_words)
                if end > len(raw):
                    continue
                phrase_slice = raw[i:end]
                if not all(piece.kind == "word" for piece in phrase_slice):
                    continue
                lowered = tuple(piece.value.lower() for piece in phrase_slice)
                if lowered == phrase_words:
                    merged.append(Token("op", replacement, token.line, token.col))
                    i = end
                    matched = True
                    break

            if matched:
                continue

            word_lower = token.value.lower()
            if word_lower in self.WORD_OPS:
                merged.append(Token("op", self.WORD_OPS[word_lower], token.line, token.col))
            elif word_lower == "true":
                merged.append(Token("name", "True", token.line, token.col))
            elif word_lower == "false":
                merged.append(Token("name", "False", token.line, token.col))
            elif word_lower == "none":
                merged.append(Token("name", "None", token.line, token.col))
            else:
                merged.append(Token("name", token.value, token.line, token.col))
            i += 1

        return merged

    def to_python_expression(self, text: str, line: int) -> str:
        cached = self._python_expr_cache.get(text)
        if cached is not None:
            self.stats.cache_hits += 1
            return cached

        self.stats.cache_misses += 1
        tokens = self.tokenize(text, line)
        py_expr = " ".join(token.value for token in tokens)
        self._python_expr_cache[text] = py_expr
        return py_expr


def normalize_assignment_sugar(line: str) -> str:
    """Intent-mode helper for x = y syntax."""

    assignment = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", line.strip())
    if assignment:
        return f"{assignment.group(1)} is like {assignment.group(2)}"
    return line
