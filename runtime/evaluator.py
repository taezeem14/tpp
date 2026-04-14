from __future__ import annotations

import ast
from typing import Any

from tpp.core.constants import SAFE_GLOBAL_NAMES
from tpp.core.errors import RuntimeTppError
from tpp.parser.lexer import ExpressionTokenizer
from tpp.runtime.environment import Scope


class ExpressionEvaluator:
    """Expression evaluator that walks AST nodes without Python eval."""

    ALLOWED_AST_NODES = (
        ast.Expression,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.Call,
        ast.Attribute,
        ast.Subscript,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.Set,
        ast.keyword,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Mod,
        ast.Pow,
        ast.And,
        ast.Or,
        ast.Not,
        ast.UAdd,
        ast.USub,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.In,
        ast.NotIn,
        ast.Slice,
        ast.Index,
    )

    def __init__(self, engine: RuntimeEngine) -> None:
        self.engine = engine
        self.tokenizer = ExpressionTokenizer()
        self._ast_cache: dict[str, ast.Expression] = {}

    def evaluate(self, expr: str, scope: Scope, line: int) -> Any:
        text = expr.strip()
        if not text:
            raise RuntimeTppError("Missing expression.", line)

        py_expr = self.tokenizer.to_python_expression(text, line)
        tree = self._ast_cache.get(py_expr)
        if tree is None:
            try:
                parsed = ast.parse(py_expr, mode="eval")
            except SyntaxError as exc:
                raise RuntimeTppError("I could not understand this expression.", line) from exc

            for node in ast.walk(parsed):
                if not isinstance(node, self.ALLOWED_AST_NODES):
                    raise RuntimeTppError("That expression uses unsupported syntax.", line)

            tree = parsed
            self._ast_cache[py_expr] = tree

        return self._eval_node(tree.body, scope, line)

    def _eval_node(self, node: ast.AST, scope: Scope, line: int) -> Any:
        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Name):
            if node.id in SAFE_GLOBAL_NAMES:
                return SAFE_GLOBAL_NAMES[node.id]
            return scope.get(node.id, line)

        if isinstance(node, ast.List):
            return [self._eval_node(element, scope, line) for element in node.elts]

        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(element, scope, line) for element in node.elts)

        if isinstance(node, ast.Set):
            return {self._eval_node(element, scope, line) for element in node.elts}

        if isinstance(node, ast.Dict):
            result: dict[Any, Any] = {}
            for key_node, value_node in zip(node.keys, node.values):
                if key_node is None:
                    raise RuntimeTppError("Dictionary unpacking is not supported.", line)
                key = self._eval_node(key_node, scope, line)
                value = self._eval_node(value_node, scope, line)
                result[key] = value
            return result

        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, scope, line)
            right = self._eval_node(node.right, scope, line)
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
            raise RuntimeTppError("Unsupported binary operation.", line)

        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand, scope, line)
            if isinstance(node.op, ast.Not):
                return not operand
            if isinstance(node.op, ast.UAdd):
                return +operand
            if isinstance(node.op, ast.USub):
                return -operand
            raise RuntimeTppError("Unsupported unary operation.", line)

        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                last = None
                for value_node in node.values:
                    last = self._eval_node(value_node, scope, line)
                    if not last:
                        return last
                return last
            if isinstance(node.op, ast.Or):
                last = None
                for value_node in node.values:
                    last = self._eval_node(value_node, scope, line)
                    if last:
                        return last
                return last
            raise RuntimeTppError("Unsupported boolean operation.", line)

        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, scope, line)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, scope, line)
                if isinstance(op, ast.Eq):
                    ok = left == right
                elif isinstance(op, ast.NotEq):
                    ok = left != right
                elif isinstance(op, ast.Lt):
                    ok = left < right
                elif isinstance(op, ast.LtE):
                    ok = left <= right
                elif isinstance(op, ast.Gt):
                    ok = left > right
                elif isinstance(op, ast.GtE):
                    ok = left >= right
                elif isinstance(op, ast.In):
                    ok = left in right
                elif isinstance(op, ast.NotIn):
                    ok = left not in right
                else:
                    raise RuntimeTppError("Unsupported comparison operation.", line)
                if not ok:
                    return False
                left = right
            return True

        if isinstance(node, ast.Attribute):
            target = self._eval_node(node.value, scope, line)
            if not hasattr(target, node.attr):
                raise RuntimeTppError(f"Target has no member named '{node.attr}'.", line)
            return getattr(target, node.attr)

        if isinstance(node, ast.Subscript):
            target = self._eval_node(node.value, scope, line)
            if isinstance(node.slice, ast.Slice):
                start = self._eval_node(node.slice.lower, scope, line) if node.slice.lower else None
                stop = self._eval_node(node.slice.upper, scope, line) if node.slice.upper else None
                step = self._eval_node(node.slice.step, scope, line) if node.slice.step else None
                return target[slice(start, stop, step)]

            index = self._eval_node(node.slice, scope, line)
            return target[index]

        if isinstance(node, ast.Call):
            target = self._eval_node(node.func, scope, line)
            args = [self._eval_node(arg, scope, line) for arg in node.args]
            kwargs = {kw.arg: self._eval_node(kw.value, scope, line) for kw in node.keywords if kw.arg is not None}
            return self.engine.invoke_target(target, args, line, kwargs=kwargs)

        raise RuntimeTppError("That expression uses unsupported syntax.", line)


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tpp.runtime.engine import RuntimeEngine
