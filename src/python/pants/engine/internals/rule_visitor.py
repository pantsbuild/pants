# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import ast
import inspect
import itertools
import logging
import sys
from contextlib import contextmanager
from functools import partial
from typing import Any, Callable, Iterator, List, get_type_hints

import typing_extensions

from pants.base.exceptions import RuleTypeError
from pants.engine.internals.selectors import (
    Awaitable,
    AwaitableConstraints,
    Effect,
    GetParseError,
    MultiGet,
)
from pants.util.memo import memoized
from pants.util.strutil import softwrap
from pants.util.typing import patch_forward_ref

logger = logging.getLogger(__name__)
patch_forward_ref()


def _get_starting_indent(source: str) -> int:
    """Used to remove leading indentation from `source` so ast.parse() doesn't raise an
    exception."""
    if source.startswith(" "):
        return sum(1 for _ in itertools.takewhile(lambda c: c in {" ", b" "}, source))
    return 0


def _node_str(node: Any) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return ".".join([_node_str(node.value), node.attr])
    if isinstance(node, ast.Call):
        return _node_str(node.func)
    if sys.version_info[0:2] < (3, 8):
        if isinstance(node, ast.Str):
            return node.s
    else:
        if isinstance(node, ast.Constant):
            return str(node.value)
    return str(node)


class _TypeStack:
    def __init__(self, func: Callable) -> None:
        self._stack: list[dict[str, Any]] = []
        self.root = sys.modules[func.__module__]
        self.push(self.root)
        self._push_function_closures(func)

    def __getitem__(self, name: str) -> Any:
        for ns in reversed(self._stack):
            if name in ns:
                return ns[name]
        return self.root.__builtins__.get(name, None)

    def __setitem__(self, name: str, value: Any) -> None:
        self._stack[-1][name] = value

    def _push_function_closures(self, func: Callable) -> None:
        try:
            closurevars = [c for c in inspect.getclosurevars(func) if isinstance(c, dict)]
        except ValueError:
            return

        for closures in closurevars:
            self.push(closures)

    def push(self, frame: object) -> None:
        ns = dict(frame if isinstance(frame, dict) else frame.__dict__)
        self._stack.append(ns)

    def pop(self) -> None:
        assert len(self._stack) > 1
        self._stack.pop()


def _lookup_annotation(obj: Any, attr: str) -> Any:
    """Get type associated with a particular attribute on object. This can get hairy, especially on
    Python <3.10.

    https://docs.python.org/3/howto/annotations.html#accessing-the-annotations-dict-of-an-object-in-python-3-9-and-older
    """
    if hasattr(obj, attr):
        return getattr(obj, attr)
    else:
        try:
            return get_type_hints(obj).get(attr)
        except (NameError, TypeError):
            return None


def _lookup_return_type(func: Callable, check: bool = False) -> Any:
    ret = _lookup_annotation(func, "return")
    typ = typing_extensions.get_origin(ret)
    if isinstance(typ, type):
        args = typing_extensions.get_args(ret)
        if issubclass(typ, (list, set, tuple)):
            return tuple(args)
    if check and ret is None:
        func_file = inspect.getsourcefile(func)
        func_line = func.__code__.co_firstlineno
        raise TypeError(
            f"Failed to look up return type hint for `{func.__name__}` in {func_file}:{func_line}"
        )
    return ret


def _returns_awaitable(func: Any) -> bool:
    if not callable(func):
        return False
    ret = _lookup_return_type(func)
    if not isinstance(ret, tuple):
        ret = (ret,)
    return any(issubclass(r, Awaitable) for r in ret if isinstance(r, type))


class _AwaitableCollector(ast.NodeVisitor):
    def __init__(self, func: Callable):
        self.func = func
        source = inspect.getsource(func) or "<string>"
        beginning_indent = _get_starting_indent(source)
        if beginning_indent:
            source = "\n".join(line[beginning_indent:] for line in source.split("\n"))

        self.source_file = inspect.getsourcefile(func)

        self.types = _TypeStack(func)
        self.awaitables: List[AwaitableConstraints] = []
        self.visit(ast.parse(source))

    def _format(self, node: ast.AST, msg: str) -> str:
        lineno = node.lineno + self.func.__code__.co_firstlineno - 1
        return f"{self.source_file}:{lineno}: {msg}"

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
        result = self.types[name]
        while result is not None and names:
            result = _lookup_annotation(result, names.pop())
        return result

    def _missing_type_error(self, node: ast.AST, context: str) -> str:
        mod = self.types.root.__name__
        return self._format(
            node,
            softwrap(
                f"""
                Could not resolve type for `{_node_str(node)}` in module {mod}.

                {context}
                """
            ),
        )

    def _check_constraint_arg_type(self, resolved: Any, node: ast.AST) -> type:
        if resolved is None:
            raise RuleTypeError(
                self._missing_type_error(
                    node, context="This may be a limitation of the Pants rule type inference."
                )
            )
        elif not isinstance(resolved, type):
            raise RuleTypeError(
                self._format(
                    node,
                    f"Expected a type, but got: {type(resolved).__name__} {_node_str(resolved)!r}",
                )
            )
        return resolved

    def _get_awaitable(self, call_node: ast.Call, is_effect: bool) -> AwaitableConstraints:
        get_args = call_node.args
        parse_error = partial(GetParseError, get_args=get_args, source_file_name=self.source_file)

        if len(get_args) not in (2, 3):
            # TODO: fix parse error message formatting... (TODO: create ticket)
            raise parse_error(
                self._format(
                    call_node,
                    f"Expected either two or three arguments, but got {len(get_args)} arguments.",
                )
            )

        output_node = get_args[0]
        output_type = self._lookup(output_node)

        input_nodes = get_args[1:]
        input_types: List[Any]
        if len(input_nodes) == 1:
            input_constructor = input_nodes[0]
            if isinstance(input_constructor, ast.Call):
                cls_or_func = self._lookup(input_constructor.func)
                try:
                    type_ = (
                        _lookup_return_type(cls_or_func, check=True)
                        if not isinstance(cls_or_func, type)
                        else cls_or_func
                    )
                except TypeError as e:
                    raise RuleTypeError(self._missing_type_error(input_constructor, str(e))) from e
                input_nodes = [input_constructor.func]
                input_types = [type_]
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
        func = self._lookup(call_node.func)
        if func is not None:
            if isinstance(func, type) and issubclass(func, Awaitable):
                self.awaitables.append(
                    self._get_awaitable(call_node, is_effect=issubclass(func, Effect))
                )
            elif inspect.iscoroutinefunction(func) or _returns_awaitable(func):
                self.awaitables.extend(collect_awaitables(func))

        self.generic_visit(call_node)

    def visit_AsyncFunctionDef(self, rule: ast.AsyncFunctionDef) -> None:
        with self._visit_rule_args(rule.args):
            self.generic_visit(rule)

    def visit_FunctionDef(self, rule: ast.FunctionDef) -> None:
        with self._visit_rule_args(rule.args):
            self.generic_visit(rule)

    @contextmanager
    def _visit_rule_args(self, node: ast.arguments) -> Iterator[None]:
        self.types.push(
            {
                a.arg: self.types[a.annotation.id]
                for a in node.args
                if isinstance(a.annotation, ast.Name)
            }
        )
        try:
            yield
        finally:
            self.types.pop()

    def visit_Assign(self, assign_node: ast.Assign) -> None:
        awaitables_idx = len(self.awaitables)
        self.generic_visit(assign_node)
        collected_awaitables = self.awaitables[awaitables_idx:]
        value = None
        node: ast.AST = assign_node
        while True:
            if isinstance(node, (ast.Assign, ast.Await)):
                node = node.value
                continue
            if isinstance(node, ast.Call):
                f = self._lookup(node.func)
                if f is MultiGet:
                    value = tuple(get.output_type for get in collected_awaitables)
                elif f is not None:
                    value = _lookup_return_type(f)
            elif isinstance(node, (ast.Name, ast.Attribute)):
                value = self._lookup(node)
            break

        for tgt in assign_node.targets:
            if isinstance(tgt, ast.Name):
                names = [tgt.id]
                values = [value]
            elif isinstance(tgt, ast.Tuple):
                names = [el.id for el in tgt.elts if isinstance(el, ast.Name)]
                values = value or itertools.cycle([None])  # type: ignore[assignment]
            else:
                # subscript, etc..
                continue
            try:
                for name, value in zip(names, values):
                    self.types[name] = value
            except TypeError as e:
                logger.debug(
                    self._format(
                        node,
                        softwrap(
                            f"""
                            Rule visitor failed to inspect assignment expression for
                            {names} - {values}:

                            {e}
                            """
                        ),
                    )
                )


@memoized
def collect_awaitables(func: Callable) -> List[AwaitableConstraints]:
    return _AwaitableCollector(func).awaitables
