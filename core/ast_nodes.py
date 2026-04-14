from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Program:
    statements: list[Any]


@dataclass
class ImportModuleStmt:
    line: int
    module: str
    alias: Optional[str]


@dataclass
class ImportFromStmt:
    line: int
    name: str
    module: str
    alias: Optional[str]


@dataclass
class SayStmt:
    line: int
    parts: list[str]


@dataclass
class AskStmt:
    line: int
    target: str
    prompt_expr: Optional[str]


@dataclass
class LetStmt:
    line: int
    name: str
    expr: str


@dataclass
class SmartAssignStmt:
    line: int
    name: str
    expr: str


@dataclass
class ChangeStmt:
    line: int
    name: str
    expr: str


@dataclass
class IfStmt:
    line: int
    branches: list[tuple[str, list[Any]]]
    else_body: list[Any]


@dataclass
class WhileStmt:
    line: int
    condition: str
    body: list[Any]


@dataclass
class ForEachStmt:
    line: int
    var_name: str
    iterable_expr: str
    body: list[Any]


@dataclass
class RepeatStmt:
    line: int
    count_expr: str
    body: list[Any]


@dataclass
class CountStmt:
    line: int
    var_name: str
    start_expr: str
    end_expr: str
    body: list[Any]


@dataclass
class BreakStmt:
    line: int


@dataclass
class ContinueStmt:
    line: int


@dataclass
class PassStmt:
    line: int


@dataclass
class FunctionDefStmt:
    line: int
    name: str
    params: list[str]
    body: list[Any]


@dataclass
class ReturnStmt:
    line: int
    expr: Optional[str]


@dataclass
class ExprStmt:
    line: int
    expr: str


@dataclass
class AddToStmt:
    line: int
    value_expr: str
    target_name: str
    force_set: bool


@dataclass
class RemoveFromStmt:
    line: int
    value_expr: str
    target_name: str
    force_set: bool


@dataclass
class DictSetStmt:
    line: int
    key_expr: str
    map_name: str
    value_expr: str


@dataclass
class ClassDefStmt:
    line: int
    name: str
    init_method: Optional[FunctionDefStmt]
    methods: list[FunctionDefStmt]


@dataclass
class RememberStmt:
    line: int
    name: str


@dataclass
class TestStmt:
    line: int
    name: str
    body: list[Any]


@dataclass
class TestSuiteStmt:
    line: int
    name: str
    tests: list[TestStmt]


@dataclass
class ExpectEqualStmt:
    line: int
    left_expr: str
    right_expr: str


@dataclass
class ExpectTypeStmt:
    line: int
    expr: str
    expected_type: str


@dataclass
class ExpectRangeStmt:
    line: int
    expr: str
    low_expr: str
    high_expr: str


@dataclass
class RegisterKeywordStmt:
    line: int
    phrase: str
    template: Optional[str]


@dataclass
class DescribeStmt:
    line: int
    description: str


@dataclass
class CreateWindowStmt:
    line: int
    title_expr: str
    window_name: Optional[str]


@dataclass
class SetWindowSizeStmt:
    line: int
    width_expr: str
    height_expr: str
    window_name: Optional[str]


@dataclass
class CreateButtonStmt:
    line: int
    label_expr: str
    button_name: Optional[str]
    window_name: Optional[str]


@dataclass
class OnButtonClickStmt:
    line: int
    button_name: Optional[str]
    body: list[Any]


@dataclass
class ShowWindowStmt:
    line: int
    window_name: Optional[str]


@dataclass
class Token:
    kind: str
    value: str
    line: int
    col: int
