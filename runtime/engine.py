from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from tpp import __version__
from tpp.core.ast_nodes import (
    AddToStmt,
    AskStmt,
    BreakStmt,
    ChangeStmt,
    ClassDefStmt,
    ContinueStmt,
    CountStmt,
    CreateButtonStmt,
    CreateWindowStmt,
    DescribeStmt,
    DictSetStmt,
    ExpectEqualStmt,
    ExpectRangeStmt,
    ExpectTypeStmt,
    ExprStmt,
    ForEachStmt,
    FunctionDefStmt,
    IfStmt,
    ImportFromStmt,
    ImportModuleStmt,
    LetStmt,
    OnButtonClickStmt,
    PassStmt,
    Program,
    RegisterKeywordStmt,
    RememberStmt,
    RemoveFromStmt,
    RepeatStmt,
    ReturnStmt,
    SayStmt,
    SetWindowSizeStmt,
    ShowWindowStmt,
    SmartAssignStmt,
    TestStmt,
    TestSuiteStmt,
    WhileStmt,
)
from tpp.core.constants import ALLOWED_PYTHON_MODULES, CORE_STATEMENT_STARTERS
from tpp.core.errors import (
    BreakSignal,
    ContinueSignal,
    ReturnSignal,
    RuntimeTppError,
    SecurityTppError,
    TppError,
)
from tpp.core.utils import is_identifier, split_key_value, split_natural_args, split_top_level, split_top_level_once
from tpp.gui.framework import GuiRuntime
from tpp.parser import Optimizer, Parser, ParserConfig, SemanticAnalyzer, SemanticConfig
from tpp.plugins import PluginManager
from tpp.runtime.environment import BoundMethod, LazyValue, Scope, TppClass, TppFunction, TppInstance
from tpp.runtime.evaluator import ExpressionEvaluator
from tpp.runtime.interop import SafePythonInterop
from tpp.runtime.profiler import RuntimeProfiler
from tpp.stdlib import NativeModule, create_native_stdlib_registry


@dataclass
class EngineConfig:
    parser_mode: str = "fuzzy"
    debug_trace: bool = False
    optimize: bool = True
    profiling: bool = False
    strict_semantic_resolution: bool = False
    allow_python_bridge: bool = True
    sandbox_base_dir: Optional[Path] = None


@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    details: Optional[str] = None


class RuntimeEngine:
    def __init__(self, config: Optional[EngineConfig] = None) -> None:
        self.config = config or EngineConfig()
        self.base_dir = (self.config.sandbox_base_dir or Path.cwd()).resolve()

        self.global_scope = Scope()
        self.parser_semantic = SemanticAnalyzer(
            SemanticConfig(strict_variable_resolution=self.config.strict_semantic_resolution)
        )
        self.optimizer = Optimizer()
        self.profiler = RuntimeProfiler(enabled=self.config.profiling)
        self.interop = SafePythonInterop()
        self.plugin_manager = PluginManager()
        self.gui = GuiRuntime()

        self.native_stdlib = create_native_stdlib_registry(self.base_dir)
        self.program_cache: dict[tuple[str, str, bool, int], Program] = {}

        self.evaluator = ExpressionEvaluator(self)

    def _plugin_signature(self) -> int:
        return (
            len(self.plugin_manager.loaded_plugins) * 13
            + len(self.plugin_manager.keyword_rewrites) * 7
            + len(self.plugin_manager.ast_transforms) * 3
        )

    def register_keyword(self, phrase: str, template: Optional[str]) -> None:
        norm = " ".join(phrase.strip().lower().split())
        self.plugin_manager.keywords.add(norm)
        if template is not None:
            self.plugin_manager.keyword_rewrites[norm] = template
        self.program_cache.clear()

    def load_plugin(self, path: str) -> None:
        self.plugin_manager.load_file(path)
        self.program_cache.clear()

    def parse_source(self, source: str, *, repl_mode: bool = False) -> Program:
        cache_key = (source, self.config.parser_mode, repl_mode, self._plugin_signature())
        cached = self.program_cache.get(cache_key)
        if cached is not None:
            return cached

        rewrites, keywords = self.plugin_manager.snapshot_keywords()
        parser = Parser(
            source,
            config=ParserConfig(mode=self.config.parser_mode, repl_mode=repl_mode),
            plugin_rewrites=rewrites,
            plugin_keywords=keywords,
        )
        program = parser.parse()
        program = self.plugin_manager.apply_ast_transforms(program)

        self.parser_semantic.analyze(program)

        if self.config.optimize:
            program = self.optimizer.optimize(program)

        if len(self.program_cache) > 256:
            self.program_cache.clear()
        self.program_cache[cache_key] = program
        return program

    def run_source(self, source: str, *, repl_mode: bool = False) -> None:
        program = self.parse_source(source, repl_mode=repl_mode)
        self.execute_program(program)

    def execute_program(self, program: Program) -> None:
        self.execute_block(program.statements, self.global_scope)

    def execute_block(self, statements: list[Any], scope: Scope, *, test_context: bool = False) -> None:
        for statement in statements:
            label = type(statement).__name__
            with self.profiler.measure(label):
                self.execute_statement(statement, scope, test_context=test_context)

    def execute_statement(self, stmt: Any, scope: Scope, *, test_context: bool = False) -> None:
        if isinstance(stmt, ImportModuleStmt):
            self.execute_import_module(stmt, scope)
            return

        if isinstance(stmt, ImportFromStmt):
            self.execute_import_from(stmt, scope)
            return

        if isinstance(stmt, SayStmt):
            values = [self.evaluate_expression(part, scope, stmt.line) for part in stmt.parts]
            print(*values)
            return

        if isinstance(stmt, AskStmt):
            prompt = ""
            if stmt.prompt_expr is not None:
                prompt = str(self.evaluate_expression(stmt.prompt_expr, scope, stmt.line))
            value = input(prompt)
            if scope.has_in_chain(stmt.target):
                scope.assign_existing(stmt.target, value, stmt.line)
            else:
                scope.define(stmt.target, value)
            return

        if isinstance(stmt, LetStmt):
            value = self.evaluate_expression(stmt.expr, scope, stmt.line)
            scope.define(stmt.name, value)
            return

        if isinstance(stmt, SmartAssignStmt):
            value = self.evaluate_expression(stmt.expr, scope, stmt.line)
            if scope.has_in_chain(stmt.name):
                scope.assign_existing(stmt.name, value, stmt.line)
            else:
                scope.define(stmt.name, value)
            return

        if isinstance(stmt, ChangeStmt):
            value = self.evaluate_expression(stmt.expr, scope, stmt.line)
            scope.assign_existing(stmt.name, value, stmt.line)
            return

        if isinstance(stmt, IfStmt):
            for condition_expr, body in stmt.branches:
                condition = self.evaluate_expression(condition_expr, scope, stmt.line)
                if bool(condition):
                    self.execute_block(body, scope, test_context=test_context)
                    return
            if stmt.else_body:
                self.execute_block(stmt.else_body, scope, test_context=test_context)
            return

        if isinstance(stmt, WhileStmt):
            while bool(self.evaluate_expression(stmt.condition, scope, stmt.line)):
                try:
                    self.execute_block(stmt.body, scope, test_context=test_context)
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
            return

        if isinstance(stmt, ForEachStmt):
            iterable = self.evaluate_expression(stmt.iterable_expr, scope, stmt.line)
            try:
                iterator = iter(iterable)
            except TypeError as exc:
                raise RuntimeTppError("'for each' needs something iterable.", stmt.line) from exc
            for item in iterator:
                if scope.has_in_chain(stmt.var_name):
                    scope.assign_existing(stmt.var_name, item, stmt.line)
                else:
                    scope.define(stmt.var_name, item)
                try:
                    self.execute_block(stmt.body, scope, test_context=test_context)
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
            return

        if isinstance(stmt, RepeatStmt):
            count_value = self.evaluate_expression(stmt.count_expr, scope, stmt.line)
            try:
                count = int(count_value)
            except (TypeError, ValueError) as exc:
                raise RuntimeTppError("'repeat' count must be a whole number.", stmt.line) from exc
            for _ in range(max(0, count)):
                try:
                    self.execute_block(stmt.body, scope, test_context=test_context)
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
            return

        if isinstance(stmt, CountStmt):
            start_value = self.evaluate_expression(stmt.start_expr, scope, stmt.line)
            end_value = self.evaluate_expression(stmt.end_expr, scope, stmt.line)
            try:
                start = int(start_value)
                end = int(end_value)
            except (TypeError, ValueError) as exc:
                raise RuntimeTppError("'count from ... to ...' needs whole numbers.", stmt.line) from exc

            step = 1 if end >= start else -1
            stop = end + step
            for value in range(start, stop, step):
                if scope.has_in_chain(stmt.var_name):
                    scope.assign_existing(stmt.var_name, value, stmt.line)
                else:
                    scope.define(stmt.var_name, value)
                try:
                    self.execute_block(stmt.body, scope, test_context=test_context)
                except ContinueSignal:
                    continue
                except BreakSignal:
                    break
            return

        if isinstance(stmt, BreakStmt):
            raise BreakSignal()

        if isinstance(stmt, ContinueStmt):
            raise ContinueSignal()

        if isinstance(stmt, PassStmt):
            return

        if isinstance(stmt, FunctionDefStmt):
            scope.define(stmt.name, TppFunction(stmt.name, stmt.params, stmt.body, scope, is_method=False))
            return

        if isinstance(stmt, ReturnStmt):
            if stmt.expr is None:
                raise ReturnSignal(None)
            raise ReturnSignal(self.evaluate_expression(stmt.expr, scope, stmt.line))

        if isinstance(stmt, ExprStmt):
            self.evaluate_expression(stmt.expr, scope, stmt.line)
            return

        if isinstance(stmt, AddToStmt):
            value = self.evaluate_expression(stmt.value_expr, scope, stmt.line)
            target = scope.get(stmt.target_name, stmt.line)
            if stmt.force_set:
                if not isinstance(target, set):
                    raise RuntimeTppError(f"'{stmt.target_name}' is not a set.", stmt.line)
                target.add(value)
                return
            if isinstance(target, list):
                target.append(value)
                return
            if isinstance(target, set):
                target.add(value)
                return
            raise RuntimeTppError(f"'{stmt.target_name}' is not a list or set.", stmt.line)

        if isinstance(stmt, RemoveFromStmt):
            value = self.evaluate_expression(stmt.value_expr, scope, stmt.line)
            target = scope.get(stmt.target_name, stmt.line)
            if stmt.force_set:
                if not isinstance(target, set):
                    raise RuntimeTppError(f"'{stmt.target_name}' is not a set.", stmt.line)
                if value not in target:
                    raise RuntimeTppError(f"'{value}' is not in set '{stmt.target_name}'.", stmt.line)
                target.remove(value)
                return
            if isinstance(target, list):
                if value not in target:
                    raise RuntimeTppError(f"'{value}' is not in list '{stmt.target_name}'.", stmt.line)
                target.remove(value)
                return
            if isinstance(target, set):
                if value not in target:
                    raise RuntimeTppError(f"'{value}' is not in set '{stmt.target_name}'.", stmt.line)
                target.remove(value)
                return
            raise RuntimeTppError(f"'{stmt.target_name}' is not a list or set.", stmt.line)

        if isinstance(stmt, DictSetStmt):
            map_obj = scope.get(stmt.map_name, stmt.line)
            if not isinstance(map_obj, dict):
                raise RuntimeTppError(f"'{stmt.map_name}' is not a map.", stmt.line)
            key = self.evaluate_expression(stmt.key_expr, scope, stmt.line)
            value = self.evaluate_expression(stmt.value_expr, scope, stmt.line)
            map_obj[key] = value
            return

        if isinstance(stmt, ClassDefStmt):
            init_method: Optional[TppFunction] = None
            if stmt.init_method is not None:
                init_method = TppFunction(
                    name="__init__",
                    params=stmt.init_method.params,
                    body=stmt.init_method.body,
                    closure=scope,
                    is_method=True,
                )

            methods: dict[str, TppFunction] = {}
            for method_stmt in stmt.methods:
                methods[method_stmt.name] = TppFunction(
                    name=method_stmt.name,
                    params=method_stmt.params,
                    body=method_stmt.body,
                    closure=scope,
                    is_method=True,
                )

            scope.define(stmt.name, TppClass(stmt.name, init_method, methods))
            return

        if isinstance(stmt, RememberStmt):
            if scope.self_obj is None:
                raise RuntimeTppError("'remember' only works inside class methods.", stmt.line)
            value = scope.get(stmt.name, stmt.line)
            scope.self_obj.fields[stmt.name] = value
            return

        if isinstance(stmt, RegisterKeywordStmt):
            self.register_keyword(stmt.phrase, stmt.template)
            return

        if isinstance(stmt, DescribeStmt):
            print(self.generate_tpp_from_description(stmt.description))
            return

        if isinstance(stmt, CreateWindowStmt):
            title = str(self.evaluate_expression(stmt.title_expr, scope, stmt.line))
            handle = self.gui.create_window(title, stmt.window_name)
            if stmt.window_name:
                scope.define(stmt.window_name, handle)
            return

        if isinstance(stmt, SetWindowSizeStmt):
            width = int(self.evaluate_expression(stmt.width_expr, scope, stmt.line))
            height = int(self.evaluate_expression(stmt.height_expr, scope, stmt.line))
            self.gui.set_window_size(width, height, stmt.window_name)
            return

        if isinstance(stmt, CreateButtonStmt):
            label = str(self.evaluate_expression(stmt.label_expr, scope, stmt.line))
            handle = self.gui.create_button(label, stmt.button_name, stmt.window_name)
            if stmt.button_name:
                scope.define(stmt.button_name, handle)
            return

        if isinstance(stmt, OnButtonClickStmt):
            def callback() -> None:
                callback_scope = Scope(parent=scope)
                self.execute_block(stmt.body, callback_scope)

            self.gui.on_button_click(callback, stmt.button_name)
            return

        if isinstance(stmt, ShowWindowStmt):
            self.gui.show_window(stmt.window_name)
            return

        if isinstance(stmt, (TestStmt, TestSuiteStmt)):
            # Normal execution ignores tests.
            return

        if isinstance(stmt, ExpectEqualStmt):
            if not test_context:
                raise RuntimeTppError("Expect statements can only run in test mode.", stmt.line)
            left = self.evaluate_expression(stmt.left_expr, scope, stmt.line)
            right = self.evaluate_expression(stmt.right_expr, scope, stmt.line)
            if left != right:
                raise RuntimeTppError(
                    f"Expectation failed. Left was {left!r} but right was {right!r}.",
                    stmt.line,
                )
            return

        if isinstance(stmt, ExpectTypeStmt):
            if not test_context:
                raise RuntimeTppError("Expect statements can only run in test mode.", stmt.line)
            value = self.evaluate_expression(stmt.expr, scope, stmt.line)
            actual = type(value).__name__
            if actual != stmt.expected_type:
                raise RuntimeTppError(
                    f"Type expectation failed. Got '{actual}', expected '{stmt.expected_type}'.",
                    stmt.line,
                )
            return

        if isinstance(stmt, ExpectRangeStmt):
            if not test_context:
                raise RuntimeTppError("Expect statements can only run in test mode.", stmt.line)
            value = self.evaluate_expression(stmt.expr, scope, stmt.line)
            low = self.evaluate_expression(stmt.low_expr, scope, stmt.line)
            high = self.evaluate_expression(stmt.high_expr, scope, stmt.line)
            if not (low <= value <= high):
                raise RuntimeTppError(
                    f"Range expectation failed. Value {value!r} not in [{low!r}, {high!r}].",
                    stmt.line,
                )
            return

        raise RuntimeTppError("Unknown statement encountered.", None)

    def execute_import_module(self, stmt: ImportModuleStmt, scope: Scope) -> None:
        root = stmt.module.split(".")[0]
        alias = stmt.alias if stmt.alias else root

        if root in self.native_stdlib and stmt.module == root:
            scope.define(alias, self.native_stdlib[root])
            return

        if not self.config.allow_python_bridge:
            raise SecurityTppError("Python bridge imports are disabled in this runtime.", stmt.line)

        if root not in ALLOWED_PYTHON_MODULES:
            raise SecurityTppError(f"Module '{stmt.module}' is not allowed.", stmt.line)
        scope.define(alias, self.interop.import_module(stmt.module, stmt.line))

    def execute_import_from(self, stmt: ImportFromStmt, scope: Scope) -> None:
        root = stmt.module.split(".")[0]
        alias = stmt.alias if stmt.alias else stmt.name

        if root in self.native_stdlib and stmt.module == root:
            module = self.native_stdlib[root]
            if not module.has_member(stmt.name):
                raise RuntimeTppError(f"'{stmt.module}' has no member named '{stmt.name}'.", stmt.line)
            scope.define(alias, module.member(stmt.name))
            return

        if not self.config.allow_python_bridge:
            raise SecurityTppError("Python bridge imports are disabled in this runtime.", stmt.line)

        if root not in ALLOWED_PYTHON_MODULES:
            raise SecurityTppError(f"Module '{stmt.module}' is not allowed.", stmt.line)

        scope.define(alias, self.interop.import_from(stmt.module, stmt.name, stmt.line))

    def evaluate_expression(self, expr: str, scope: Scope, line: int) -> Any:
        text = expr.strip()
        if text == "":
            raise RuntimeTppError("Missing expression.", line)

        lowered = text.lower()

        if lowered.startswith("lazy "):
            inner_expr = text[5:].strip()
            return LazyValue(lambda: self.evaluate_expression(inner_expr, scope, line))

        if lowered in {"nothing", "none"}:
            return None

        my_match = re.match(r"^my\s+([A-Za-z_][A-Za-z0-9_]*)$", text, re.IGNORECASE)
        if my_match:
            if scope.self_obj is None:
                raise RuntimeTppError("'my' can only be used inside class methods.", line)
            field_name = my_match.group(1)
            if field_name not in scope.self_obj.fields:
                raise RuntimeTppError(f"I don't understand '{field_name}'.", line)
            return scope.self_obj.fields[field_name]

        if lowered.startswith("call "):
            return self.evaluate_call_expression(text[5:].strip(), scope, line)

        if lowered.startswith("run "):
            target_text = text[4:].strip()
            return self.call_named_target(target_text, [], scope, line)

        new_match = re.match(r"^a\s+new\s+([A-Za-z_][A-Za-z0-9_]*)(?:\s+with\s+(.+))?$", text, re.IGNORECASE)
        if new_match:
            class_name = new_match.group(1)
            args_text = new_match.group(2) or ""
            args = [self.evaluate_expression(part, scope, line) for part in split_natural_args(args_text)]
            target = scope.get(class_name, line)
            return self.invoke_target(target, args, line)

        list_match = re.match(r"^a\s+list\s+of\s*(.*)$", text, re.IGNORECASE)
        if list_match:
            content = list_match.group(1).strip()
            if content == "":
                return []
            parts = split_top_level(content, ",")
            return [self.evaluate_expression(part, scope, line) for part in parts if part]

        set_match = re.match(r"^a\s+set\s+of\s*(.*)$", text, re.IGNORECASE)
        if set_match:
            content = set_match.group(1).strip()
            if content == "":
                return set()
            parts = split_top_level(content, ",")
            return {self.evaluate_expression(part, scope, line) for part in parts if part}

        map_match = re.match(r"^a\s+map\s+of\s*(.*)$", text, re.IGNORECASE)
        if map_match:
            content = map_match.group(1).strip()
            if content == "":
                return {}
            map_obj: dict[Any, Any] = {}
            for pair_text in split_top_level(content, ","):
                split = split_key_value(pair_text)
                if split is None:
                    raise RuntimeTppError("Map entries must look like key: value.", line)
                key = self.evaluate_expression(split[0], scope, line)
                value = self.evaluate_expression(split[1], scope, line)
                map_obj[key] = value
            return map_obj

        length_match = re.match(r"^the\s+length\s+of\s+(.+)$", text, re.IGNORECASE)
        if length_match:
            target_value = self.evaluate_expression(length_match.group(1).strip(), scope, line)
            return len(target_value)

        map_get_match = re.match(r"^the\s+(.+)\s+of\s+(.+)$", text, re.IGNORECASE)
        if map_get_match:
            key = self.evaluate_expression(map_get_match.group(1).strip(), scope, line)
            target = self.evaluate_expression(map_get_match.group(2).strip(), scope, line)
            if isinstance(target, dict):
                if key not in target:
                    raise RuntimeTppError(f"Key '{key}' is missing.", line)
                return target[key]
            if isinstance(target, TppInstance) and isinstance(key, str):
                return target.resolve_member(key, line)
            return target[key]

        return self.evaluator.evaluate(text, scope, line)

    def evaluate_call_expression(self, call_text: str, scope: Scope, line: int) -> Any:
        on_split = split_top_level_once(call_text, " on ")
        if on_split is not None:
            method_name, target_portion = on_split
            method_name = method_name.strip()
            if not is_identifier(method_name):
                raise RuntimeTppError("Method name after 'call' must be a valid identifier.", line)

            with_split = split_top_level_once(target_portion, " with ")
            if with_split is None:
                target_expr = target_portion.strip()
                args_text = ""
            else:
                target_expr, args_text = with_split

            target_obj = self.evaluate_expression(target_expr, scope, line)
            method_target = self.resolve_member(target_obj, method_name, line)
            args = [self.evaluate_expression(part, scope, line) for part in split_natural_args(args_text)]
            return self.invoke_target(method_target, args, line)

        with_split = split_top_level_once(call_text, " with ")
        if with_split is None:
            target_expr = call_text.strip()
            args_text = ""
        else:
            target_expr, args_text = with_split

        args = [self.evaluate_expression(part, scope, line) for part in split_natural_args(args_text)]
        return self.call_named_target(target_expr, args, scope, line)

    def call_named_target(self, target_expr: str, args: list[Any], scope: Scope, line: int) -> Any:
        target_expr = target_expr.strip()
        if target_expr == "":
            raise RuntimeTppError("Missing call target.", line)

        if is_identifier(target_expr):
            target = scope.get(target_expr, line)
        else:
            target = self.evaluate_expression(target_expr, scope, line)
        return self.invoke_target(target, args, line)

    def resolve_member(self, target_obj: Any, member_name: str, line: int) -> Any:
        if isinstance(target_obj, TppInstance):
            return target_obj.resolve_member(member_name, line)
        if isinstance(target_obj, NativeModule):
            if target_obj.has_member(member_name):
                return target_obj.member(member_name)
            raise RuntimeTppError(f"Target has no member named '{member_name}'.", line)
        if not hasattr(target_obj, member_name):
            raise RuntimeTppError(f"Target has no member named '{member_name}'.", line)
        return getattr(target_obj, member_name)

    def invoke_target(self, target: Any, args: list[Any], line: int, kwargs: Optional[dict[str, Any]] = None) -> Any:
        kwargs = kwargs or {}
        if isinstance(target, BoundMethod):
            if kwargs:
                raise RuntimeTppError("Keyword arguments are not supported for bound methods.", line)
            return target.invoke(self, args, line)
        if isinstance(target, TppFunction):
            if kwargs:
                raise RuntimeTppError("Keyword arguments are not supported for T++ functions.", line)
            return target.invoke(self, args, line)
        if isinstance(target, TppClass):
            if kwargs:
                raise RuntimeTppError("Keyword arguments are not supported for class constructors.", line)
            return target.instantiate(self, args, line)
        if callable(target):
            try:
                return target(*args, **kwargs)
            except Exception as exc:
                raise RuntimeTppError(str(exc), line) from exc
        raise RuntimeTppError("That value is not callable.", line)

    def collect_tests(self, program: Program) -> list[TestStmt]:
        tests: list[TestStmt] = []
        for statement in program.statements:
            if isinstance(statement, TestStmt):
                tests.append(statement)
            elif isinstance(statement, TestSuiteStmt):
                tests.extend(statement.tests)
        return tests

    def run_tests(self, program: Program, *, verbose: bool = False) -> tuple[list[TestResult], int, int]:
        setup_statements = [
            statement
            for statement in program.statements
            if not isinstance(statement, (TestStmt, TestSuiteStmt))
        ]
        self.execute_block(setup_statements, self.global_scope)

        test_results: list[TestResult] = []
        tests = self.collect_tests(program)
        for test_case in tests:
            test_scope = Scope(parent=self.global_scope)
            started = time.perf_counter()
            try:
                self.execute_block(test_case.body, test_scope, test_context=True)
            except TppError as exc:
                elapsed = (time.perf_counter() - started) * 1000
                test_results.append(TestResult(name=test_case.name, passed=False, duration_ms=elapsed, details=str(exc)))
                continue
            except Exception as exc:
                elapsed = (time.perf_counter() - started) * 1000
                test_results.append(
                    TestResult(
                        name=test_case.name,
                        passed=False,
                        duration_ms=elapsed,
                        details=f"Unexpected error: {exc}",
                    )
                )
                continue

            elapsed = (time.perf_counter() - started) * 1000
            test_results.append(TestResult(name=test_case.name, passed=True, duration_ms=elapsed))

        passed = sum(1 for result in test_results if result.passed)
        failed = len(test_results) - passed

        if verbose:
            for result in test_results:
                status = "PASS" if result.passed else "FAIL"
                print(f"[{status}] {result.name} ({result.duration_ms:.1f} ms)")
                if result.details:
                    print(f"       {result.details}")

        return test_results, passed, failed

    def manifest(self) -> dict[str, Any]:
        return {
            "name": "T++",
            "version": __version__,
            "runtime": "tpp-runtime",
            "parser_modes": ["strict", "fuzzy", "intent"],
            "keywords": sorted(CORE_STATEMENT_STARTERS | self.plugin_manager.keywords),
            "python_bridge_modules": sorted(ALLOWED_PYTHON_MODULES),
            "native_modules": sorted(self.native_stdlib.keys()),
            "modes": ["run", "repl", "test", "pipe", "api"],
            "examples": [
                "let x be 5",
                "increase x by 2",
                "create window titled \"My App\"",
                "test \"addition\":",
            ],
        }

    @staticmethod
    def generate_tpp_from_description(description: str) -> str:
        lowered = description.lower()

        if "function" in lowered and "sort" in lowered:
            return "define function sort with items:\n    give back call sorted with items"

        if "function" in lowered and ("add" in lowered or "sum" in lowered):
            return "define function add with a and b:\n    give back a plus b"

        if "function" in lowered and "maximum" in lowered:
            return "define function maximum with items:\n    give back call max with items"

        if "window" in lowered or "gui" in lowered:
            return (
                "create window titled \"My App\"\n"
                "set window size to 400 by 300\n"
                "create button \"Click Me\"\n"
                "on button click:\n"
                "    say \"Hello\"\n"
                "show window"
            )

        return "define function task with no inputs:\n    do nothing"
