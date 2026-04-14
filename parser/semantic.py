from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from tpp.core.ast_nodes import (
    AskStmt,
    BreakStmt,
    ChangeStmt,
    ClassDefStmt,
    ContinueStmt,
    CountStmt,
    ExpectEqualStmt,
    ExpectRangeStmt,
    ExpectTypeStmt,
    ForEachStmt,
    FunctionDefStmt,
    IfStmt,
    LetStmt,
    OnButtonClickStmt,
    Program,
    RegisterKeywordStmt,
    RememberStmt,
    RepeatStmt,
    ReturnStmt,
    SmartAssignStmt,
    TestStmt,
    TestSuiteStmt,
    WhileStmt,
)
from tpp.core.errors import SemanticTppError
from tpp.core.utils import suggest_closest


@dataclass
class SemanticConfig:
    strict_variable_resolution: bool = False


@dataclass
class SemanticContext:
    in_loop: bool = False
    in_function: bool = False
    in_class_method: bool = False
    in_test: bool = False
    symbols: set[str] = field(default_factory=set)


class SemanticAnalyzer:
    def __init__(self, config: Optional[SemanticConfig] = None) -> None:
        self.config = config or SemanticConfig()
        self.inferred_types: dict[str, str] = {}

    def analyze(self, program: Program) -> dict[str, str]:
        context = SemanticContext(symbols=set())
        for statement in program.statements:
            self._visit(statement, context)
        return dict(self.inferred_types)

    def _visit(self, stmt: Any, context: SemanticContext) -> None:
        if isinstance(stmt, IfStmt):
            for _condition, body in stmt.branches:
                self._visit_block(body, self._fork_context(context))
            self._visit_block(stmt.else_body, self._fork_context(context))
            return

        if isinstance(stmt, WhileStmt):
            inner = self._fork_context(context, in_loop=True)
            self._visit_block(stmt.body, inner)
            return

        if isinstance(stmt, ForEachStmt):
            inner = self._fork_context(context, in_loop=True)
            inner.symbols.add(stmt.var_name)
            self.inferred_types.setdefault(stmt.var_name, "Any")
            self._visit_block(stmt.body, inner)
            return

        if isinstance(stmt, RepeatStmt):
            inner = self._fork_context(context, in_loop=True)
            self._visit_block(stmt.body, inner)
            return

        if isinstance(stmt, CountStmt):
            inner = self._fork_context(context, in_loop=True)
            inner.symbols.add(stmt.var_name)
            self.inferred_types[stmt.var_name] = "int"
            self._visit_block(stmt.body, inner)
            return

        if isinstance(stmt, FunctionDefStmt):
            context.symbols.add(stmt.name)
            fn_ctx = self._fork_context(context, in_function=True)
            for param in stmt.params:
                fn_ctx.symbols.add(param)
                self.inferred_types.setdefault(param, "Any")
            self._visit_block(stmt.body, fn_ctx)
            return

        if isinstance(stmt, ClassDefStmt):
            context.symbols.add(stmt.name)
            if stmt.init_method is not None:
                init_ctx = self._fork_context(context, in_function=True, in_class_method=True)
                for param in stmt.init_method.params:
                    init_ctx.symbols.add(param)
                self._visit_block(stmt.init_method.body, init_ctx)
            for method in stmt.methods:
                method_ctx = self._fork_context(context, in_function=True, in_class_method=True)
                for param in method.params:
                    method_ctx.symbols.add(param)
                self._visit_block(method.body, method_ctx)
            return

        if isinstance(stmt, TestSuiteStmt):
            for test in stmt.tests:
                self._visit(test, self._fork_context(context, in_test=True))
            return

        if isinstance(stmt, TestStmt):
            self._visit_block(stmt.body, self._fork_context(context, in_test=True))
            return

        if isinstance(stmt, OnButtonClickStmt):
            self._visit_block(stmt.body, self._fork_context(context, in_function=True))
            return

        if isinstance(stmt, LetStmt):
            context.symbols.add(stmt.name)
            self.inferred_types[stmt.name] = self._infer_type(stmt.expr)
            return

        if isinstance(stmt, SmartAssignStmt):
            context.symbols.add(stmt.name)
            self.inferred_types[stmt.name] = self._infer_type(stmt.expr)
            return

        if isinstance(stmt, AskStmt):
            context.symbols.add(stmt.target)
            self.inferred_types[stmt.target] = "str"
            return

        if isinstance(stmt, ChangeStmt):
            if stmt.name not in context.symbols and self.config.strict_variable_resolution:
                suggestion = suggest_closest(stmt.name, context.symbols)
                raise SemanticTppError(
                    f"Variable '{stmt.name}' is not defined before change.",
                    stmt.line,
                    suggestion=f"Did you mean '{suggestion}'?" if suggestion else "Declare it first with let.",
                )
            return

        if isinstance(stmt, BreakStmt) and not context.in_loop:
            raise SemanticTppError("'stop loop' can only be used inside a loop.", stmt.line)

        if isinstance(stmt, ContinueStmt) and not context.in_loop:
            raise SemanticTppError("'skip' can only be used inside a loop.", stmt.line)

        if isinstance(stmt, ReturnStmt) and not context.in_function:
            raise SemanticTppError("'give back' can only be used inside a function.", stmt.line)

        if isinstance(stmt, RememberStmt) and not context.in_class_method:
            raise SemanticTppError("'remember' only works inside class methods.", stmt.line)

        if isinstance(stmt, (ExpectEqualStmt, ExpectTypeStmt, ExpectRangeStmt)) and not context.in_test:
            raise SemanticTppError("Expect statements can only be used inside test blocks.", stmt.line)

        if isinstance(stmt, RegisterKeywordStmt):
            return

    def _visit_block(self, statements: list[Any], context: SemanticContext) -> None:
        for statement in statements:
            self._visit(statement, context)

    @staticmethod
    def _fork_context(
        context: SemanticContext,
        *,
        in_loop: Optional[bool] = None,
        in_function: Optional[bool] = None,
        in_class_method: Optional[bool] = None,
        in_test: Optional[bool] = None,
    ) -> SemanticContext:
        return SemanticContext(
            in_loop=context.in_loop if in_loop is None else in_loop,
            in_function=context.in_function if in_function is None else in_function,
            in_class_method=context.in_class_method if in_class_method is None else in_class_method,
            in_test=context.in_test if in_test is None else in_test,
            symbols=set(context.symbols),
        )

    @staticmethod
    def _infer_type(expr: str) -> str:
        text = expr.strip()
        lowered = text.lower()
        if lowered in {"true", "false"}:
            return "bool"
        if lowered in {"nothing", "none"}:
            return "None"
        if text.startswith(("\"", "'")) and text.endswith(("\"", "'")) and len(text) >= 2:
            return "str"
        if re_int(text):
            return "int"
        if re_float(text):
            return "float"
        if lowered.startswith("a list of"):
            return "list"
        if lowered.startswith("a set of"):
            return "set"
        if lowered.startswith("a map of"):
            return "dict"
        return "Any"


def re_int(text: str) -> bool:
    try:
        int(text)
        return True
    except ValueError:
        return False


def re_float(text: str) -> bool:
    try:
        float(text)
        return "." in text
    except ValueError:
        return False
