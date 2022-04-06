# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import ast
import inspect
import itertools
import logging
import sys
import types
from functools import partial
from typing import Callable, List, cast

from pants.engine.internals.selectors import AwaitableConstraints, GetParseError
from pants.util.memo import memoized

logger = logging.getLogger(__name__)


def _is_awaitable_constraint(call_node: ast.Call) -> bool:
    return isinstance(call_node.func, ast.Name) and call_node.func.id in ("Get", "Effect")


def _get_starting_indent(source: str) -> int:
    """Used to remove leading indentation from `source` so ast.parse() doesn't raise an
    exception."""
    if source.startswith(" "):
        return sum(1 for _ in itertools.takewhile(lambda c: c in {" ", b" "}, source))
    return 0


def _get_lookup_names(attr: ast.expr):
    names = []
    while isinstance(attr, ast.Attribute):
        names.append(attr.attr)
        attr = attr.value
    # NB: attr could be a constant, like `",".join()`
    names.append(getattr(attr, "id", None))
    return names


class _AwaitableCollector(ast.NodeVisitor):
    def __init__(self, func: Callable):
        self.func = func
        source = inspect.getsource(func) or "<string>"
        beginning_indent = _get_starting_indent(source)
        if beginning_indent:
            source = "\n".join(line[beginning_indent:] for line in source.split("\n"))

        self.source_file = inspect.getsourcefile(func)

        self.owning_module = sys.modules[func.__module__]
        self.awaitables: List[AwaitableConstraints] = []
        self.visit(ast.parse(source))

    def _resolve_constrain_arg_type(self, name: str, lineno: int) -> type:
        lineno += self.func.__code__.co_firstlineno - 1
        resolved = (
            getattr(self.owning_module, name, None)
            or self.owning_module.__builtins__.get(name, None)  # type: ignore[attr-defined]
        )  # fmt: skip
        if resolved is None:
            raise ValueError(
                f"Could not resolve type `{name}` in top level of module "
                f"{self.owning_module.__name__} defined in {self.source_file}:{lineno}"
            )
        elif not isinstance(resolved, type):
            raise ValueError(
                f"Expected a `type` constructor for `{name}`, but got: {resolved} (type "
                f"`{type(resolved).__name__}`) in {self.source_file}:{lineno}"
            )
        return resolved

    def _get_awaitable(self, call_node: ast.Call) -> AwaitableConstraints:
        assert isinstance(call_node.func, ast.Name)
        is_effect = call_node.func.id == "Effect"
        get_args = call_node.args
        parse_error = partial(GetParseError, get_args=get_args, source_file_name=self.source_file)

        if len(get_args) not in (2, 3):
            raise parse_error(
                f"Expected either two or three arguments, but got {len(get_args)} arguments."
            )

        output_expr = get_args[0]
        if not isinstance(output_expr, ast.Name):
            raise parse_error(
                "The first argument should be the output type, like `Digest` or `ProcessResult`."
            )
        output_type = output_expr

        input_args = get_args[1:]
        input_type: ast.Name
        if len(input_args) == 1:
            input_constructor = input_args[0]
            if not isinstance(input_constructor, ast.Call):
                raise parse_error(
                    f"Because you are using the shorthand form {call_node.func.id}(OutputType, "
                    "InputType(constructor args), the second argument should be a constructor "
                    "call, like `MergeDigest(...)` or `Process(...)`."
                )
            if not isinstance(input_constructor.func, ast.Name):
                raise parse_error(
                    f"Because you are using the shorthand form {call_node.func.id}(OutputType, "
                    "InputType(constructor args), the second argument should be a top-level "
                    "constructor function call, like `MergeDigest(...)` or `Process(...)`, rather "
                    "than a method call."
                )
            input_type = input_constructor.func
        else:
            if not isinstance(input_args[0], ast.Name):
                raise parse_error(
                    f"Because you are using the longhand form {call_node.func.id}(OutputType, "
                    "InputType, input), the second argument should be a type, like `MergeDigests` or "
                    "`Process`."
                )
            input_type = input_args[0]

        return AwaitableConstraints(
            self._resolve_constrain_arg_type(output_type.id, output_type.lineno),
            self._resolve_constrain_arg_type(input_type.id, input_type.lineno),
            is_effect,
        )

    def visit_Call(self, call_node: ast.Call) -> None:
        if _is_awaitable_constraint(call_node):
            self.awaitables.append(self._get_awaitable(call_node))
        else:
            func_node = call_node.func
            lookup_names = _get_lookup_names(func_node)
            attr = cast(types.FunctionType, self.func).__globals__.get(lookup_names.pop(), None)
            while attr is not None and lookup_names:
                attr = getattr(attr, lookup_names.pop(), None)

            if hasattr(attr, "rule_helper"):
                self.awaitables.extend(collect_awaitables(attr))

        self.generic_visit(call_node)


@memoized
def collect_awaitables(func: Callable) -> List[AwaitableConstraints]:
    return _AwaitableCollector(func).awaitables
