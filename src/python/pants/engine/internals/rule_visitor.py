# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import ast
import inspect
import itertools
import logging
import sys
from functools import partial
from typing import Any, Callable, List

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

    def _lookup(self, attr: ast.expr) -> Any:
        names = []
        while isinstance(attr, ast.Attribute):
            names.append(attr.attr)
            attr = attr.value
        # NB: attr could be a constant, like `",".join()`
        id = getattr(attr, "id", None)
        if id is not None:
            names.append(id)

        if not names:
            return attr

        name = names.pop()
        result = (
            getattr(self.owning_module, name)
            if hasattr(self.owning_module, name)
            else self.owning_module.__builtins__.get(name, None)
        )
        while result is not None and names:
            result = getattr(result, names.pop(), None)

        return result

    def _check_constraint_arg_type(self, resolved: Any, node: ast.AST) -> type:
        lineno = node.lineno + self.func.__code__.co_firstlineno - 1
        if resolved is None:
            raise ValueError(
                f"Could not resolve type `{node}` in top level of module "
                f"{self.owning_module.__name__} defined in {self.source_file}:{lineno}"
            )
        elif not isinstance(resolved, type):
            raise ValueError(
                f"Expected a `type`, but got: {resolved}"
                + f" (type `{type(resolved).__name__}`) in {self.source_file}:{lineno}"
            )
        return resolved

    def _get_awaitable(self, call_node: ast.Call) -> AwaitableConstraints:
        func = self._lookup(call_node.func)
        is_effect = func.__name__ == "Effect"
        get_args = call_node.args
        parse_error = partial(GetParseError, get_args=get_args, source_file_name=self.source_file)

        if len(get_args) not in (2, 3):
            raise parse_error(
                f"Expected either two or three arguments, but got {len(get_args)} arguments."
            )

        output_node = get_args[0]
        output_type = self._lookup(output_node)

        input_nodes = get_args[1:]
        input_types: List[Any]
        if len(input_nodes) == 1:
            input_constructor = input_nodes[0]
            if isinstance(input_constructor, ast.Call):
                input_nodes = [input_constructor.func]
                input_types = [self._lookup(input_constructor.func)]
            elif isinstance(input_constructor, ast.Dict):
                input_nodes = input_constructor.values
                input_types = [self._lookup(v) for v in input_constructor.values]
            else:
                input_types = [self._lookup(n) for n in input_nodes]
        else:
            input_types = [self._lookup(input_nodes[0])]

        return AwaitableConstraints(
            self._check_constraint_arg_type(output_type, output_node),
            tuple(
                self._check_constraint_arg_type(input_type, input_node)
                for input_type, input_node in zip(input_types, input_nodes)
            ),
            is_effect,
        )

    def visit_Call(self, call_node: ast.Call) -> None:
        if _is_awaitable_constraint(call_node):
            self.awaitables.append(self._get_awaitable(call_node))
        else:
            attr = self._lookup(call_node.func)
            if hasattr(attr, "rule_helper"):
                self.awaitables.extend(collect_awaitables(attr))

        self.generic_visit(call_node)


@memoized
def collect_awaitables(func: Callable) -> List[AwaitableConstraints]:
    return _AwaitableCollector(func).awaitables
