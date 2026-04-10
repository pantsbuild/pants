# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import ast
import inspect
import itertools
import logging
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from types import ModuleType
from typing import Any, get_type_hints

import typing_extensions

from pants.base.exceptions import RuleTypeError
from pants.engine.internals.selectors import (
    AwaitableConstraints,
    concurrently,
)
from pants.util.memo import memoized
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


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


PANTS_RULE_DESCRIPTORS_MODULE_KEY = "__pants_rule_descriptors__"


@dataclass(frozen=True)
class RuleDescriptor:
    """The data we glean about a rule by examining its AST.

    This will be lazily invoked in the first `@rule` decorator in a module. Therefore it will parse
    the AST *before* the module code is fully evaluated, and so the return type may not yet exist as
    a parsed type. So we store it here as a str and look it up later.
    """

    module_name: str
    rule_name: str
    return_type: str

    @property
    def rule_id(self) -> str:
        # TODO: Handle canonical_name/canonical_name_suffix?
        return f"{self.module_name}.{self.rule_name}"


def get_module_scope_rules(module: ModuleType) -> tuple[RuleDescriptor, ...]:
    """Get descriptors for @rules defined at the top level of the given module.

    We discover these top-level rules and rule helpers in the module by examining the AST.
    This means that while executing the `@rule` decorator of a rule1(), the descriptor of a rule2()
    defined later in the module is already known.  This allows rule1() and rule2() to be
    mutually recursive.

    Note that we don't support recursive rules defined dynamically in inner scopes.
    """
    descriptors = getattr(module, PANTS_RULE_DESCRIPTORS_MODULE_KEY, None)
    if descriptors is None:
        descriptors = []
        for node in ast.iter_child_nodes(ast.parse(inspect.getsource(module))):
            if isinstance(node, ast.AsyncFunctionDef) and isinstance(node.returns, ast.Name):
                descriptors.append(RuleDescriptor(module.__name__, node.name, node.returns.id))
        descriptors = tuple(descriptors)
        setattr(module, PANTS_RULE_DESCRIPTORS_MODULE_KEY, descriptors)

    return descriptors


class _TypeStack:
    """The types and rules that a @rule can refer to in its input/outputs, or its awaitables.

    We construct this data through a mix of inspection of types already parsed by Python,
    and descriptors we infer from the AST. This allows us to support mutual recursion between
    rules defined in the same module (the @rule descriptor of the earlier rule can know enough
    about the later rule it calls to set up its own awaitables correctly).

    This logic is necessarily heuristic. It works for well-behaved code, but may be defeated
    by metaprogramming, aliasing, shadowing and so on.
    """

    def __init__(self, func: Callable) -> None:
        self._stack: list[dict[str, Any]] = []
        self.root = sys.modules[func.__module__]

        # We fall back to descriptors last, so that we get parsed objects whenever possible,
        # as those are less susceptible to limitations of the heuristics.
        self.push({descr.rule_name: descr for descr in get_module_scope_rules(self.root)})
        self.push(self.root)
        self._push_function_closures(func)
        # Rule args will be pushed later, as we handle them.

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


class _AwaitableCollector(ast.NodeVisitor):
    def __init__(self, func: Callable):
        self.func = func
        source = inspect.getsource(func) or "<string>"
        beginning_indent = _get_starting_indent(source)
        if beginning_indent:
            source = "\n".join(line[beginning_indent:] for line in source.split("\n"))

        self.source_file = inspect.getsourcefile(func) or "<unknown>"

        self.types = _TypeStack(func)
        self.awaitables: list[AwaitableConstraints] = []
        self.visit(ast.parse(source))

    def _format(self, node: ast.AST, msg: str) -> str:
        lineno: str = "<unknown>"
        if isinstance(node, (ast.expr, ast.stmt)):
            lineno = str(node.lineno + self.func.__code__.co_firstlineno - 1)
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

    def _get_inputs(self, input_nodes: Sequence[Any]) -> tuple[Sequence[Any], list[Any]]:
        if not input_nodes:
            return input_nodes, []
        if len(input_nodes) != 1:
            return input_nodes, [self._lookup(input_nodes[0])]

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
            return [input_constructor.func], [type_]
        elif isinstance(input_constructor, ast.Dict):
            return input_constructor.values, [self._lookup(v) for v in input_constructor.values]
        else:
            return input_nodes, [self._lookup(n) for n in input_nodes]

    def _get_byname_awaitable(
        self, rule_id: str, rule_func: Callable | RuleDescriptor, call_node: ast.Call
    ) -> AwaitableConstraints:
        if isinstance(rule_func, RuleDescriptor):
            # At this point we expect the return type to be defined, so its source code
            # must precede that of the rule invoking the awaitable that returns it.
            output_type = self.types[rule_func.return_type]
        else:
            output_type = _lookup_return_type(rule_func, check=True)

        # To support explicit positional arguments, we record the number passed positionally.
        # TODO: To support keyword arguments, we would additionally need to begin recording the
        # argument names of kwargs. But positional-only callsites can avoid those allocations.
        explicit_args_arity = len(call_node.args)

        input_types: tuple[type, ...]
        if not call_node.keywords:
            input_types = ()
        elif (
            len(call_node.keywords) == 1
            and not call_node.keywords[0].arg
            and isinstance(implicitly_call := call_node.keywords[0].value, ast.Call)
            and self._lookup(implicitly_call.func).__name__ == "implicitly"
        ):
            input_nodes, input_type_nodes = self._get_inputs(implicitly_call.args)
            input_types = tuple(
                self._check_constraint_arg_type(input_type, input_node)
                for input_type, input_node in zip(input_type_nodes, input_nodes)
            )
        else:
            explanation = self._format(
                call_node,
                "Expected an `**implicitly(..)` application as the only keyword input.",
            )
            raise ValueError(
                f"Invalid call. {explanation} failed in a call to {rule_id} in {self.source_file}."
            )

        return AwaitableConstraints(
            rule_id,
            output_type,
            explicit_args_arity,
            input_types,
        )

    def visit_Call(self, call_node: ast.Call) -> None:
        func = self._lookup(call_node.func)
        if func is not None:
            if (inspect.isfunction(func) or isinstance(func, RuleDescriptor)) and (
                rule_id := getattr(func, "rule_id", None)
            ) is not None:
                # Is a direct `@rule` call.
                self.awaitables.append(self._get_byname_awaitable(rule_id, func, call_node))
            elif inspect.iscoroutinefunction(func):
                # Is a call to a "rule helper".
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
                if f is concurrently:
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
def collect_awaitables(func: Callable) -> list[AwaitableConstraints]:
    return _AwaitableCollector(func).awaitables
