from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

from tpp.core.ast_nodes import (
    ChangeStmt,
    ExpectEqualStmt,
    ExpectRangeStmt,
    ExpectTypeStmt,
    ForEachStmt,
    FunctionDefStmt,
    IfStmt,
    LetStmt,
    OnButtonClickStmt,
    Program,
    RepeatStmt,
    ReturnStmt,
    SmartAssignStmt,
    TestStmt,
    TestSuiteStmt,
    WhileStmt,
)
from tpp.parser.lexer import ExpressionTokenizer


@dataclass
class OptimizerStats:
    folded_expressions: int = 0


class Optimizer:
    """Simple optimization pass with constant folding."""

    def __init__(self) -> None:
        self.tokenizer = ExpressionTokenizer()
        self.stats = OptimizerStats()

    def optimize(self, program: Program) -> Program:
        program.statements = self._optimize_block(program.statements)
        return program

    def _optimize_block(self, statements: list[Any]) -> list[Any]:
        optimized: list[Any] = []
        for stmt in statements:
            optimized.append(self._optimize_stmt(stmt))
        return optimized

    def _optimize_stmt(self, stmt: Any) -> Any:
        if isinstance(stmt, (LetStmt, SmartAssignStmt, ChangeStmt, ReturnStmt, ExpectTypeStmt)):
            if getattr(stmt, "expr", None):
                stmt.expr = self._fold_expression(stmt.expr, stmt.line)
            return stmt

        if isinstance(stmt, ExpectEqualStmt):
            stmt.left_expr = self._fold_expression(stmt.left_expr, stmt.line)
            stmt.right_expr = self._fold_expression(stmt.right_expr, stmt.line)
            return stmt

        if isinstance(stmt, ExpectRangeStmt):
            stmt.expr = self._fold_expression(stmt.expr, stmt.line)
            stmt.low_expr = self._fold_expression(stmt.low_expr, stmt.line)
            stmt.high_expr = self._fold_expression(stmt.high_expr, stmt.line)
            return stmt

        if isinstance(stmt, IfStmt):
            stmt.branches = [(self._fold_expression(cond, stmt.line), self._optimize_block(body)) for cond, body in stmt.branches]
            stmt.else_body = self._optimize_block(stmt.else_body)
            return stmt

        if isinstance(stmt, WhileStmt):
            stmt.condition = self._fold_expression(stmt.condition, stmt.line)
            stmt.body = self._optimize_block(stmt.body)
            return stmt

        if isinstance(stmt, ForEachStmt):
            stmt.iterable_expr = self._fold_expression(stmt.iterable_expr, stmt.line)
            stmt.body = self._optimize_block(stmt.body)
            return stmt

        if isinstance(stmt, RepeatStmt):
            stmt.count_expr = self._fold_expression(stmt.count_expr, stmt.line)
            stmt.body = self._optimize_block(stmt.body)
            return stmt

        if isinstance(stmt, FunctionDefStmt):
            stmt.body = self._optimize_block(stmt.body)
            return stmt

        if isinstance(stmt, TestStmt):
            stmt.body = self._optimize_block(stmt.body)
            return stmt

        if isinstance(stmt, TestSuiteStmt):
            for test in stmt.tests:
                test.body = self._optimize_block(test.body)
            return stmt

        if isinstance(stmt, OnButtonClickStmt):
            stmt.body = self._optimize_block(stmt.body)
            return stmt

        return stmt

    def _fold_expression(self, expr: str, line: int) -> str:
        text = expr.strip()
        if not text:
            return expr

        try:
            py_expr = self.tokenizer.to_python_expression(text, line)
            tree = ast.parse(py_expr, mode="eval")
        except Exception:
            return expr

        try:
            folded = self._safe_const_eval(tree.body)
        except Exception:
            return expr

        self.stats.folded_expressions += 1
        return repr(folded)

    def _safe_const_eval(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.UnaryOp):
            value = self._safe_const_eval(node.operand)
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return +value
            if isinstance(node.op, ast.Not):
                return not value
            raise ValueError("Unsupported unary op")

        if isinstance(node, ast.BinOp):
            left = self._safe_const_eval(node.left)
            right = self._safe_const_eval(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            if isinstance(node.op, ast.Pow):
                return left**right
            raise ValueError("Unsupported binary op")

        if isinstance(node, ast.BoolOp):
            values = [self._safe_const_eval(v) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise ValueError("Unsupported bool op")

        if isinstance(node, ast.Compare) and len(node.ops) == 1 and len(node.comparators) == 1:
            left = self._safe_const_eval(node.left)
            right = self._safe_const_eval(node.comparators[0])
            op = node.ops[0]
            if isinstance(op, ast.Eq):
                return left == right
            if isinstance(op, ast.NotEq):
                return left != right
            if isinstance(op, ast.Lt):
                return left < right
            if isinstance(op, ast.LtE):
                return left <= right
            if isinstance(op, ast.Gt):
                return left > right
            if isinstance(op, ast.GtE):
                return left >= right
            raise ValueError("Unsupported compare")

        if isinstance(node, ast.List):
            return [self._safe_const_eval(e) for e in node.elts]

        if isinstance(node, ast.Tuple):
            return tuple(self._safe_const_eval(e) for e in node.elts)

        if isinstance(node, ast.Set):
            return {self._safe_const_eval(e) for e in node.elts}

        if isinstance(node, ast.Dict):
            return {
                self._safe_const_eval(k): self._safe_const_eval(v)
                for k, v in zip(node.keys, node.values)
                if k is not None
            }

        raise ValueError("Non-constant expression")
