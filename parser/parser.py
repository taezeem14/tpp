from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

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
from tpp.core.constants import CORE_STATEMENT_STARTERS, DEFAULT_REWRITE_LIMIT, PARSER_MODES
from tpp.core.errors import IncompleteBlockError, SyntaxTppError
from tpp.core.utils import (
    is_identifier,
    normalize_phrase,
    parse_quoted_string,
    split_natural_args,
    split_top_level,
    suggest_closest,
)
from tpp.parser.lexer import normalize_assignment_sugar


@dataclass
class ParserConfig:
    mode: str = "fuzzy"
    repl_mode: bool = False


class Parser:
    def __init__(
        self,
        source: str,
        *,
        config: Optional[ParserConfig] = None,
        plugin_rewrites: Optional[dict[str, str]] = None,
        plugin_keywords: Optional[set[str]] = None,
    ) -> None:
        self.config = config or ParserConfig()
        if self.config.mode not in PARSER_MODES:
            raise SyntaxTppError(f"Unknown parser mode '{self.config.mode}'.")

        self.lines: list[tuple[int, str]] = [
            (index + 1, line.rstrip("\n")) for index, line in enumerate(source.splitlines())
        ]
        self.plugin_rewrites = plugin_rewrites or {}
        self.plugin_keywords = plugin_keywords or set()
        self._refresh_plugin_phrase_order()

    @property
    def fuzzy_mode(self) -> bool:
        return self.config.mode in {"fuzzy", "intent"}

    @property
    def intent_mode(self) -> bool:
        return self.config.mode == "intent"

    def _refresh_plugin_phrase_order(self) -> None:
        self._plugin_phrases_sorted = sorted(self.plugin_rewrites.keys(), key=len, reverse=True)

    def parse(self) -> Program:
        statements, index = self.parse_block(0, 0)
        while index < len(self.lines):
            line_no, text = self.lines[index]
            if text.strip() == "":
                index += 1
                continue
            raise SyntaxTppError("Unexpected content after end of block.", line_no)
        return Program(statements)

    def parse_block(self, index: int, indent: int) -> tuple[list[Any], int]:
        statements: list[Any] = []
        while index < len(self.lines):
            line_no, raw_line = self.lines[index]
            if raw_line.strip() == "":
                index += 1
                continue

            line_indent = self.count_indent(raw_line, line_no)
            if line_indent < indent:
                break
            if line_indent > indent:
                raise SyntaxTppError(
                    "Indentation looks incorrect here. This line is indented more than expected.",
                    line_no,
                    suggestion="Make sure block lines share the same indent width.",
                )

            stripped = raw_line.strip()
            lowered = stripped.lower()
            if lowered.startswith("but if ") or lowered == "otherwise:":
                break

            statement, index = self.parse_statement(index, indent)
            statements.append(statement)

        return statements, index

    def parse_statement(self, index: int, indent: int) -> tuple[Any, int]:
        line_no, raw_line = self.lines[index]
        text = raw_line.strip()

        if self.intent_mode:
            text = normalize_assignment_sugar(text)

        register_stmt = self.try_parse_register_keyword(text, line_no)
        if register_stmt is not None:
            self.plugin_keywords.add(normalize_phrase(register_stmt.phrase))
            if register_stmt.template is not None:
                self.plugin_rewrites[normalize_phrase(register_stmt.phrase)] = register_stmt.template
                self._refresh_plugin_phrase_order()
            return register_stmt, index + 1

        text = self.apply_plugin_rewrites(text, line_no)

        suite_match = re.match(r"^suite\s+(.+):$", text, re.IGNORECASE)
        if suite_match:
            suite_name = parse_quoted_string(suite_match.group(1).strip(), line_no, "Suite name")
            suite_body, next_index = self.parse_child_block(index + 1, indent, line_no)
            tests = [stmt for stmt in suite_body if isinstance(stmt, TestStmt)]
            invalid = [stmt for stmt in suite_body if not isinstance(stmt, TestStmt)]
            if invalid:
                raise SyntaxTppError("A test suite may only contain test blocks.", line_no)
            return TestSuiteStmt(line=line_no, name=suite_name, tests=tests), next_index

        test_match = re.match(r"^test\s+(.+):$", text, re.IGNORECASE)
        if test_match:
            raw_name = test_match.group(1).strip()
            test_name = parse_quoted_string(raw_name, line_no, "Test name")
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return TestStmt(line=line_no, name=test_name, body=body), next_index

        expect_type_match = re.match(r"^expect\s+type\s+of\s+(.+)\s+to\s+be\s+([A-Za-z_][A-Za-z0-9_]*)$", text, re.IGNORECASE)
        if expect_type_match:
            return (
                ExpectTypeStmt(
                    line=line_no,
                    expr=expect_type_match.group(1).strip(),
                    expected_type=expect_type_match.group(2).strip(),
                ),
                index + 1,
            )

        expect_range_match = re.match(r"^expect\s+(.+)\s+to\s+be\s+between\s+(.+)\s+and\s+(.+)$", text, re.IGNORECASE)
        if expect_range_match:
            return (
                ExpectRangeStmt(
                    line=line_no,
                    expr=expect_range_match.group(1).strip(),
                    low_expr=expect_range_match.group(2).strip(),
                    high_expr=expect_range_match.group(3).strip(),
                ),
                index + 1,
            )

        expect_equal_match = re.match(r"^expect\s+(.+)\s+to\s+be\s+(.+)$", text, re.IGNORECASE)
        if expect_equal_match:
            return (
                ExpectEqualStmt(
                    line=line_no,
                    left_expr=expect_equal_match.group(1).strip(),
                    right_expr=expect_equal_match.group(2).strip(),
                ),
                index + 1,
            )

        describe_match = re.match(r"^describe\s*:\s*(.+)$", text, re.IGNORECASE)
        if describe_match:
            return DescribeStmt(line=line_no, description=describe_match.group(1).strip()), index + 1

        fuzzy_stmt = self.try_parse_fuzzy_statement(text, line_no)
        if fuzzy_stmt is not None:
            return fuzzy_stmt, index + 1

        create_window_match = re.match(
            r"^create\s+window\s+titled\s+(.+?)(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?$",
            text,
            re.IGNORECASE,
        )
        if create_window_match:
            return (
                CreateWindowStmt(
                    line=line_no,
                    title_expr=create_window_match.group(1).strip(),
                    window_name=create_window_match.group(2),
                ),
                index + 1,
            )

        set_window_size_match = re.match(
            r"^set\s+window\s+size\s+to\s+(.+)\s+by\s+(.+?)(?:\s+for\s+([A-Za-z_][A-Za-z0-9_]*))?$",
            text,
            re.IGNORECASE,
        )
        if set_window_size_match:
            return (
                SetWindowSizeStmt(
                    line=line_no,
                    width_expr=set_window_size_match.group(1).strip(),
                    height_expr=set_window_size_match.group(2).strip(),
                    window_name=set_window_size_match.group(3),
                ),
                index + 1,
            )

        create_button_match = re.match(
            r"^create\s+button\s+(.+?)(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?(?:\s+in\s+window\s+([A-Za-z_][A-Za-z0-9_]*))?$",
            text,
            re.IGNORECASE,
        )
        if create_button_match:
            return (
                CreateButtonStmt(
                    line=line_no,
                    label_expr=create_button_match.group(1).strip(),
                    button_name=create_button_match.group(2),
                    window_name=create_button_match.group(3),
                ),
                index + 1,
            )

        on_click_match = re.match(
            r"^on\s+button\s+click(?:\s+for\s+([A-Za-z_][A-Za-z0-9_]*))?:$",
            text,
            re.IGNORECASE,
        )
        if on_click_match:
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return (
                OnButtonClickStmt(line=line_no, button_name=on_click_match.group(1), body=body),
                next_index,
            )

        show_window_match = re.match(r"^show\s+window(?:\s+([A-Za-z_][A-Za-z0-9_]*))?$", text, re.IGNORECASE)
        if show_window_match:
            return ShowWindowStmt(line=line_no, window_name=show_window_match.group(1)), index + 1

        import_from_match = re.match(
            r"^bring\s+in\s+([A-Za-z_][A-Za-z0-9_]*)\s+from\s+([A-Za-z_][A-Za-z0-9_\.]*)\s*(?:as\s+([A-Za-z_][A-Za-z0-9_]*))?$",
            text,
            re.IGNORECASE,
        )
        if import_from_match:
            return (
                ImportFromStmt(
                    line=line_no,
                    name=import_from_match.group(1),
                    module=import_from_match.group(2),
                    alias=import_from_match.group(3),
                ),
                index + 1,
            )

        import_module_alias_match = re.match(
            r"^bring\s+in\s+([A-Za-z_][A-Za-z0-9_\.]*)\s+as\s+([A-Za-z_][A-Za-z0-9_]*)$",
            text,
            re.IGNORECASE,
        )
        if import_module_alias_match:
            return (
                ImportModuleStmt(
                    line=line_no,
                    module=import_module_alias_match.group(1),
                    alias=import_module_alias_match.group(2),
                ),
                index + 1,
            )

        import_module_match = re.match(r"^bring\s+in\s+([A-Za-z_][A-Za-z0-9_\.]*)$", text, re.IGNORECASE)
        if import_module_match:
            return ImportModuleStmt(line=line_no, module=import_module_match.group(1), alias=None), index + 1

        if_match = re.match(r"^if\s+(.+):$", text, re.IGNORECASE)
        if if_match:
            branches: list[tuple[str, list[Any]]] = []
            condition = if_match.group(1).strip()
            if not condition:
                raise SyntaxTppError("I expected a condition after 'if'.", line_no)
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            branches.append((condition, body))

            else_body: list[Any] = []
            while True:
                peek = self.peek_next_non_blank(next_index)
                if peek is None:
                    break
                peek_index, peek_no, peek_text, peek_indent = peek
                if peek_indent != indent:
                    break
                but_if_match = re.match(r"^but\s+if\s+(.+):$", peek_text, re.IGNORECASE)
                if but_if_match:
                    next_condition = but_if_match.group(1).strip()
                    if not next_condition:
                        raise SyntaxTppError("I expected a condition after 'but if'.", peek_no)
                    next_body, next_index = self.parse_child_block(peek_index + 1, indent, peek_no)
                    branches.append((next_condition, next_body))
                    continue
                if re.match(r"^otherwise:$", peek_text, re.IGNORECASE):
                    else_body, next_index = self.parse_child_block(peek_index + 1, indent, peek_no)
                break

            return IfStmt(line=line_no, branches=branches, else_body=else_body), next_index

        while_match = re.match(r"^keep\s+doing\s+while\s+(.+):$", text, re.IGNORECASE)
        if while_match:
            condition = while_match.group(1).strip()
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return WhileStmt(line=line_no, condition=condition, body=body), next_index

        foreach_match = re.match(r"^for\s+each\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.+):$", text, re.IGNORECASE)
        if foreach_match:
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return (
                ForEachStmt(
                    line=line_no,
                    var_name=foreach_match.group(1),
                    iterable_expr=foreach_match.group(2).strip(),
                    body=body,
                ),
                next_index,
            )

        repeat_match = re.match(r"^repeat\s+(.+?)\s+times:$", text, re.IGNORECASE)
        if repeat_match:
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return RepeatStmt(line=line_no, count_expr=repeat_match.group(1).strip(), body=body), next_index

        count_match = re.match(
            r"^count\s+from\s+(.+?)\s+to\s+(.+?)\s+as\s+([A-Za-z_][A-Za-z0-9_]*):$",
            text,
            re.IGNORECASE,
        )
        if count_match:
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return (
                CountStmt(
                    line=line_no,
                    var_name=count_match.group(3),
                    start_expr=count_match.group(1).strip(),
                    end_expr=count_match.group(2).strip(),
                    body=body,
                ),
                next_index,
            )

        if text.lower() == "stop loop":
            return BreakStmt(line=line_no), index + 1

        if text.lower() == "skip":
            return ContinueStmt(line=line_no), index + 1

        if text.lower() == "do nothing":
            return PassStmt(line=line_no), index + 1

        function_stmt = self.parse_function_statement(text, index, indent)
        if function_stmt is not None:
            return function_stmt

        if re.match(r"^give\s+back\s+nothing$", text, re.IGNORECASE):
            return ReturnStmt(line=line_no, expr=None), index + 1

        return_expr_match = re.match(r"^give\s+back\s+(.+)$", text, re.IGNORECASE)
        if return_expr_match:
            return ReturnStmt(line=line_no, expr=return_expr_match.group(1).strip()), index + 1

        say_match = re.match(r"^say\s+(.+)$", text, re.IGNORECASE)
        if say_match:
            parts = [piece for piece in split_top_level(say_match.group(1).strip(), " then ") if piece]
            if not parts:
                raise SyntaxTppError("I expected something after 'say'.", line_no)
            return SayStmt(line=line_no, parts=parts), index + 1

        ask_into_match = re.match(r"^ask\s+into\s+([A-Za-z_][A-Za-z0-9_]*)$", text, re.IGNORECASE)
        if ask_into_match:
            return AskStmt(line=line_no, target=ask_into_match.group(1), prompt_expr=None), index + 1

        ask_match = re.match(r"^ask\s+(.+)\s+into\s+([A-Za-z_][A-Za-z0-9_]*)$", text, re.IGNORECASE)
        if ask_match:
            return (
                AskStmt(line=line_no, target=ask_match.group(2), prompt_expr=ask_match.group(1).strip()),
                index + 1,
            )

        if re.match(r"^let\s+([A-Za-z_][A-Za-z0-9_]*)\s+be\s*$", text, re.IGNORECASE):
            raise SyntaxTppError("I expected a value after 'let'.", line_no)

        let_match = re.match(r"^let\s+([A-Za-z_][A-Za-z0-9_]*)\s+be\s+(.+)$", text, re.IGNORECASE)
        if let_match:
            return LetStmt(line=line_no, name=let_match.group(1), expr=let_match.group(2).strip()), index + 1

        change_my_match = re.match(r"^change\s+my\s+([A-Za-z_][A-Za-z0-9_]*)\s+to\s+(.+)$", text, re.IGNORECASE)
        if change_my_match:
            return ChangeStmt(line=line_no, name=change_my_match.group(1), expr=change_my_match.group(2).strip()), index + 1

        if re.match(r"^change\s+([A-Za-z_][A-Za-z0-9_]*)\s+to\s*$", text, re.IGNORECASE):
            raise SyntaxTppError("I expected a value after 'change'.", line_no)

        change_match = re.match(r"^change\s+([A-Za-z_][A-Za-z0-9_]*)\s+to\s+(.+)$", text, re.IGNORECASE)
        if change_match:
            return ChangeStmt(line=line_no, name=change_match.group(1), expr=change_match.group(2).strip()), index + 1

        dict_set_match = re.match(r"^set\s+the\s+(.+)\s+of\s+([A-Za-z_][A-Za-z0-9_]*)\s+to\s+(.+)$", text, re.IGNORECASE)
        if dict_set_match:
            return (
                DictSetStmt(
                    line=line_no,
                    key_expr=dict_set_match.group(1).strip(),
                    map_name=dict_set_match.group(2),
                    value_expr=dict_set_match.group(3).strip(),
                ),
                index + 1,
            )

        add_set_match = re.match(r"^add\s+(.+)\s+to\s+set\s+([A-Za-z_][A-Za-z0-9_]*)$", text, re.IGNORECASE)
        if add_set_match:
            return (
                AddToStmt(
                    line=line_no,
                    value_expr=add_set_match.group(1).strip(),
                    target_name=add_set_match.group(2),
                    force_set=True,
                ),
                index + 1,
            )

        add_match = re.match(r"^add\s+(.+)\s+to\s+([A-Za-z_][A-Za-z0-9_]*)$", text, re.IGNORECASE)
        if add_match:
            return (
                AddToStmt(
                    line=line_no,
                    value_expr=add_match.group(1).strip(),
                    target_name=add_match.group(2),
                    force_set=False,
                ),
                index + 1,
            )

        remove_set_match = re.match(r"^remove\s+(.+)\s+from\s+set\s+([A-Za-z_][A-Za-z0-9_]*)$", text, re.IGNORECASE)
        if remove_set_match:
            return (
                RemoveFromStmt(
                    line=line_no,
                    value_expr=remove_set_match.group(1).strip(),
                    target_name=remove_set_match.group(2),
                    force_set=True,
                ),
                index + 1,
            )

        remove_match = re.match(r"^remove\s+(.+)\s+from\s+([A-Za-z_][A-Za-z0-9_]*)$", text, re.IGNORECASE)
        if remove_match:
            return (
                RemoveFromStmt(
                    line=line_no,
                    value_expr=remove_match.group(1).strip(),
                    target_name=remove_match.group(2),
                    force_set=False,
                ),
                index + 1,
            )

        class_match = re.match(r"^create\s+class\s+([A-Za-z_][A-Za-z0-9_]*):$", text, re.IGNORECASE)
        if class_match:
            class_name = class_match.group(1)
            class_indent, member_start = self.require_child_indent(index + 1, indent, line_no)
            init_method: Optional[FunctionDefStmt] = None
            methods: list[FunctionDefStmt] = []

            current = member_start
            while current < len(self.lines):
                member_no, member_raw = self.lines[current]
                if member_raw.strip() == "":
                    current += 1
                    continue
                member_indent = self.count_indent(member_raw, member_no)
                if member_indent < class_indent:
                    break
                if member_indent > class_indent:
                    raise SyntaxTppError("Indentation looks incorrect inside class body.", member_no)

                member_text = member_raw.strip()
                init_match = re.match(r"^when\s+created\s+with\s+(.+):$", member_text, re.IGNORECASE)
                if init_match:
                    if init_method is not None:
                        raise SyntaxTppError("Class constructor is already defined.", member_no)
                    params = self.parse_param_text(init_match.group(1).strip(), member_no)
                    init_body, after_init = self.parse_child_block(current + 1, class_indent, member_no)
                    init_method = FunctionDefStmt(line=member_no, name="__init__", params=params, body=init_body)
                    current = after_init
                    continue

                method_stmt = self.parse_function_statement(member_text, current, class_indent)
                if method_stmt is not None:
                    method_node, after_method = method_stmt
                    methods.append(method_node)
                    current = after_method
                    continue

                raise SyntaxTppError(
                    "Inside a class, I only understand 'when created ...' and 'define ...'.",
                    member_no,
                )

            return ClassDefStmt(line=line_no, name=class_name, init_method=init_method, methods=methods), current

        remember_match = re.match(r"^remember\s+([A-Za-z_][A-Za-z0-9_]*)$", text, re.IGNORECASE)
        if remember_match:
            return RememberStmt(line=line_no, name=remember_match.group(1)), index + 1

        if text.lower().startswith("call ") or text.lower().startswith("run "):
            return ExprStmt(line=line_no, expr=text), index + 1

        raise self.build_unknown_statement_error(text, line_no)

    def parse_function_statement(self, text: str, index: int, indent: int) -> Optional[tuple[FunctionDefStmt, int]]:
        line_no = self.lines[index][0]

        takes_match = re.match(
            r"^define\s+([A-Za-z_][A-Za-z0-9_]*)\s+that\s+takes\s+(.+):$",
            text,
            re.IGNORECASE,
        )
        if takes_match:
            params = self.parse_param_text(takes_match.group(2).strip(), line_no)
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return FunctionDefStmt(line=line_no, name=takes_match.group(1), params=params, body=body), next_index

        function_with_match = re.match(
            r"^define\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s+with\s+(.+):$",
            text,
            re.IGNORECASE,
        )
        if function_with_match:
            params = self.parse_param_text(function_with_match.group(2).strip(), line_no)
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return FunctionDefStmt(line=line_no, name=function_with_match.group(1), params=params, body=body), next_index

        function_plain_match = re.match(r"^define\s+function\s+([A-Za-z_][A-Za-z0-9_]*):$", text, re.IGNORECASE)
        if function_plain_match:
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return FunctionDefStmt(line=line_no, name=function_plain_match.group(1), params=[], body=body), next_index

        no_inputs_match = re.match(
            r"^define\s+([A-Za-z_][A-Za-z0-9_]*)\s+with\s+no\s+inputs:$",
            text,
            re.IGNORECASE,
        )
        if no_inputs_match:
            body, next_index = self.parse_child_block(index + 1, indent, line_no)
            return FunctionDefStmt(line=line_no, name=no_inputs_match.group(1), params=[], body=body), next_index

        return None

    def parse_param_text(self, params_text: str, line_no: int) -> list[str]:
        lowered = params_text.lower()
        if lowered in {"no inputs", "nothing"}:
            return []

        params = split_natural_args(params_text)
        if not params:
            return []

        for param in params:
            if not is_identifier(param):
                raise SyntaxTppError(f"'{param}' is not a valid parameter name.", line_no)
        return params

    def parse_child_block(self, index: int, parent_indent: int, header_line: int) -> tuple[list[Any], int]:
        child_indent, child_start = self.require_child_indent(index, parent_indent, header_line)
        return self.parse_block(child_start, child_indent)

    def require_child_indent(self, index: int, parent_indent: int, header_line: int) -> tuple[int, int]:
        next_info = self.peek_next_non_blank(index)
        if next_info is None:
            if self.config.repl_mode:
                raise IncompleteBlockError("I expected an indented block after ':'.", header_line)
            raise SyntaxTppError("I expected an indented block after ':'.", header_line)

        next_index, next_line, _next_text, next_indent = next_info
        if next_indent <= parent_indent:
            if self.config.repl_mode:
                raise IncompleteBlockError("I expected an indented block after ':'.", header_line)
            raise SyntaxTppError(
                "Indentation looks incorrect here. Expected an indented block.",
                next_line,
                suggestion="Indent the block by at least one level.",
            )
        return next_indent, next_index

    def peek_next_non_blank(self, index: int) -> Optional[tuple[int, int, str, int]]:
        current = index
        while current < len(self.lines):
            line_no, raw = self.lines[current]
            if raw.strip() == "":
                current += 1
                continue
            indent = self.count_indent(raw, line_no)
            return current, line_no, raw.strip(), indent
        return None

    @staticmethod
    def count_indent(raw: str, line_no: int) -> int:
        if "\t" in raw:
            raise SyntaxTppError(
                "Indentation looks incorrect here. Use spaces instead of tabs.",
                line_no,
                suggestion="Replace tab characters with spaces.",
            )
        return len(raw) - len(raw.lstrip(" "))

    def try_parse_register_keyword(self, text: str, line_no: int) -> Optional[RegisterKeywordStmt]:
        register_match = re.match(r"^register\s+keyword\s+(.+?)(?:\s+as\s+(.+))?$", text, re.IGNORECASE)
        if not register_match:
            return None

        phrase_raw = register_match.group(1).strip()
        template_raw = register_match.group(2).strip() if register_match.group(2) else None

        phrase = parse_quoted_string(phrase_raw, line_no, "Keyword phrase")
        template = parse_quoted_string(template_raw, line_no, "Keyword template") if template_raw else None
        return RegisterKeywordStmt(line=line_no, phrase=phrase, template=template)

    def try_parse_fuzzy_statement(self, text: str, line_no: int) -> Optional[Any]:
        if not self.fuzzy_mode:
            return None

        is_like_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s+is\s+like\s+(.+)$", text, re.IGNORECASE)
        if is_like_match:
            return SmartAssignStmt(line=line_no, name=is_like_match.group(1), expr=is_like_match.group(2).strip())

        increase_match = re.match(r"^increase\s+([A-Za-z_][A-Za-z0-9_]*)\s+by\s+(.+)$", text, re.IGNORECASE)
        if increase_match:
            name = increase_match.group(1)
            return ChangeStmt(line=line_no, name=name, expr=f"{name} plus ({increase_match.group(2).strip()})")

        decrease_match = re.match(r"^decrease\s+([A-Za-z_][A-Za-z0-9_]*)\s+by\s+(.+)$", text, re.IGNORECASE)
        if decrease_match:
            name = decrease_match.group(1)
            return ChangeStmt(line=line_no, name=name, expr=f"{name} minus ({decrease_match.group(2).strip()})")

        smaller_match = re.match(r"^make\s+([A-Za-z_][A-Za-z0-9_]*)\s+smaller$", text, re.IGNORECASE)
        if smaller_match:
            name = smaller_match.group(1)
            return ChangeStmt(line=line_no, name=name, expr=f"{name} minus 1")

        bigger_match = re.match(r"^make\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:bigger|larger)$", text, re.IGNORECASE)
        if bigger_match:
            name = bigger_match.group(1)
            return ChangeStmt(line=line_no, name=name, expr=f"{name} plus 1")

        if self.intent_mode:
            assign_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", text)
            if assign_match:
                return SmartAssignStmt(line=line_no, name=assign_match.group(1), expr=assign_match.group(2).strip())

        return None

    def apply_plugin_rewrites(self, text: str, line_no: int) -> str:
        current = text
        for _ in range(DEFAULT_REWRITE_LIMIT):
            rewritten = self.apply_single_plugin_rewrite(current)
            if rewritten == current:
                return current
            current = rewritten
        raise SyntaxTppError("Plugin rewrite recursion detected.", line_no)

    def apply_single_plugin_rewrite(self, text: str) -> str:
        lowered = normalize_phrase(text)
        for phrase in self._plugin_phrases_sorted:
            if not self._starts_with_phrase(lowered, phrase):
                continue
            template = self.plugin_rewrites[phrase]

            phrase_words = phrase.split()
            raw_words = text.strip().split()
            if len(raw_words) < len(phrase_words):
                continue
            rest = " ".join(raw_words[len(phrase_words) :]).strip()
            return template.replace("{rest}", rest).strip()
        return text

    @staticmethod
    def _starts_with_phrase(text: str, phrase: str) -> bool:
        if not text.startswith(phrase):
            return False
        if len(text) == len(phrase):
            return True
        return text[len(phrase)].isspace() or text[len(phrase)] in ":("

    def build_unknown_statement_error(self, text: str, line_no: int) -> SyntaxTppError:
        stripped = text.strip()
        lowered = stripped.lower()

        for phrase in sorted(self.plugin_keywords, key=len, reverse=True):
            if self._starts_with_phrase(lowered, phrase) and phrase not in self.plugin_rewrites:
                return SyntaxTppError(
                    f"Keyword '{phrase}' is registered but has no behavior.",
                    line_no,
                    suggestion="Register it with: register keyword \"...\" as \"...\"",
                )

        if "=" in stripped and all(op not in stripped for op in ("==", "!=", ">=", "<=")):
            return SyntaxTppError(
                "I expected natural assignment words.",
                line_no,
                suggestion="Try 'let name be value' or 'change name to value'.",
            )

        parts = stripped.split()
        first_word = parts[0].lower() if parts else ""

        starters = self.statement_starters()
        suggestion = suggest_closest(first_word, starters)
        if suggestion:
            return SyntaxTppError(f"I don't understand '{first_word}'.", line_no, suggestion=f"Did you mean '{suggestion}'?")

        assignment_shape = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s+.+$", stripped)
        if assignment_shape and first_word not in starters:
            variable = assignment_shape.group(1)
            return SyntaxTppError(
                f"I don't understand '{stripped}'.",
                line_no,
                fix_preview=f"let {variable} be ...",
            )

        return SyntaxTppError(f"I don't understand '{stripped}'.", line_no)

    def statement_starters(self) -> set[str]:
        starters = set(CORE_STATEMENT_STARTERS)
        for phrase in self.plugin_keywords:
            if phrase:
                starters.add(phrase.split()[0])
        return starters
