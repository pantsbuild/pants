# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import inspect
import itertools
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from types import FrameType, ModuleType
from typing import (
    Any,
    Callable,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
    get_type_hints,
)

from pants.engine.goal import Goal
from pants.engine.internals.selectors import Get as Get  # noqa: F401
from pants.engine.internals.selectors import GetConstraints
from pants.engine.internals.selectors import MultiGet as MultiGet  # noqa: F401
from pants.engine.unions import UnionRule
from pants.option.optionable import OptionableFactory
from pants.util.collections import assert_single_element
from pants.util.logging import LogLevel
from pants.util.memo import memoized
from pants.util.meta import decorated_type_checkable, frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


@decorated_type_checkable
def side_effecting(cls):
    """Annotates a class to indicate that it is a side-effecting type, which needs to be handled
    specially with respect to rule caching semantics."""
    return side_effecting.define_instance_of(cls)


class _RuleVisitor(ast.NodeVisitor):
    """Pull `Get` calls out of an @rule body."""

    def __init__(self, *, resolve_type: Callable[[str], Type[Any]], source_file_name: str) -> None:
        super().__init__()
        self.source_file_name = source_file_name
        self.resolve_type = resolve_type
        self.gets: List[GetConstraints] = []

    @staticmethod
    def maybe_extract_get_args(call_node: ast.Call) -> Optional[List[ast.expr]]:
        """Check if the node looks like a Get(T, ...) call."""
        if not isinstance(call_node.func, ast.Name):
            return None
        if call_node.func.id != "Get":
            return None
        return call_node.args

    def visit_Call(self, call_node: ast.Call) -> None:
        get_args = self.maybe_extract_get_args(call_node)
        if get_args is not None:
            product_str, subject_str = GetConstraints.parse_input_and_output_types(
                get_args, source_file_name=self.source_file_name
            )
            get = GetConstraints(self.resolve_type(product_str), self.resolve_type(subject_str))
            self.gets.append(get)
        # Ensure we descend into e.g. MultiGet(Get(...)...) calls.
        self.generic_visit(call_node)


# NB: This violates Python naming conventions of using snake_case for functions. This is because
# SubsystemRule behaves very similarly to UnionRule and RootRule, and we want to use the same
# naming scheme.
#
# We could refactor this to be a class with __call__() defined, but we would lose the `@memoized`
# decorator.
@memoized
def SubsystemRule(optionable_factory: Type[OptionableFactory]) -> TaskRule:
    """Returns a TaskRule that constructs an instance of the subsystem."""
    return TaskRule(**optionable_factory.signature())


def _get_starting_indent(source):
    """Used to remove leading indentation from `source` so ast.parse() doesn't raise an
    exception."""
    if source.startswith(" "):
        return sum(1 for _ in itertools.takewhile(lambda c: c in {" ", b" "}, source))
    return 0


class RuleType(Enum):
    rule = "rule"
    goal_rule = "goal_rule"
    uncacheable_rule = "_uncacheable_rule"


def _make_rule(
    rule_type: RuleType,
    return_type: Type,
    parameter_types: Iterable[Type],
    *,
    cacheable: bool,
    canonical_name: str,
    desc: Optional[str],
    level: LogLevel,
) -> Callable[[Callable], Callable]:
    """A @decorator that declares that a particular static function may be used as a TaskRule.

    As a special case, if the output_type is a subclass of `Goal`, the `Goal.Options` for the `Goal`
    are registered as dependency Optionables.

    :param rule_type: The specific decorator used to declare the rule.
    :param return_type: The return/output type for the Rule. This must be a concrete Python type.
    :param parameter_types: A sequence of types that matches the number and order of arguments to the
                            decorated function.
    :param cacheable: Whether the results of executing the Rule should be cached as keyed by all of
                      its inputs.
    """

    is_goal_cls = issubclass(return_type, Goal)
    if rule_type == RuleType.rule and is_goal_cls:
        raise TypeError(
            "An `@rule` that returns a `Goal` must instead be declared with `@goal_rule`."
        )
    if rule_type == RuleType.goal_rule and not is_goal_cls:
        raise TypeError("An `@goal_rule` must return a subclass of `engine.goal.Goal`.")

    def wrapper(func):
        if not inspect.isfunction(func):
            raise ValueError("The @rule decorator must be applied innermost of all decorators.")

        owning_module = sys.modules[func.__module__]
        source = inspect.getsource(func) or "<string>"
        source_file = inspect.getsourcefile(func)
        beginning_indent = _get_starting_indent(source)
        if beginning_indent:
            source = "\n".join(line[beginning_indent:] for line in source.split("\n"))
        module_ast = ast.parse(source)

        def resolve_type(name):
            resolved = getattr(owning_module, name, None) or owning_module.__builtins__.get(
                name, None
            )
            if resolved is None:
                raise ValueError(
                    f"Could not resolve type `{name}` in top level of module "
                    f"{owning_module.__name__} defined in {source_file}"
                )
            elif not isinstance(resolved, type):
                raise ValueError(
                    f"Expected a `type` constructor for `{name}`, but got: {resolved} (type "
                    f"`{type(resolved).__name__}`) in {source_file}"
                )
            return resolved

        rule_func_node = assert_single_element(
            node
            for node in ast.iter_child_nodes(module_ast)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == func.__name__
        )

        parents_table = {}
        for parent in ast.walk(rule_func_node):
            for child in ast.iter_child_nodes(parent):
                parents_table[child] = parent

        rule_visitor = _RuleVisitor(source_file_name=source_file, resolve_type=resolve_type)
        rule_visitor.visit(rule_func_node)

        gets = FrozenOrderedSet(rule_visitor.gets)

        # Set our own custom `__line_number__` dunder so that the engine may visualize the line number.
        func.__line_number__ = func.__code__.co_firstlineno

        func.rule = TaskRule(
            return_type,
            parameter_types,
            func,
            input_gets=gets,
            canonical_name=canonical_name,
            desc=desc,
            level=level,
            cacheable=cacheable,
        )

        return func

    return wrapper


class InvalidTypeAnnotation(TypeError):
    """Indicates an incorrect type annotation for an `@rule`."""


class UnrecognizedRuleArgument(TypeError):
    """Indicates an unrecognized keyword argument to a `@rule`."""


class MissingTypeAnnotation(TypeError):
    """Indicates a missing type annotation for an `@rule`."""


class MissingReturnTypeAnnotation(InvalidTypeAnnotation):
    """Indicates a missing return type annotation for an `@rule`."""


class MissingParameterTypeAnnotation(InvalidTypeAnnotation):
    """Indicates a missing parameter type annotation for an `@rule`."""


def _ensure_type_annotation(
    *,
    type_annotation: Optional[Type],
    name: str,
    raise_type: Type[InvalidTypeAnnotation],
) -> Type:
    if type_annotation is None:
        raise raise_type(f"{name} is missing a type annotation.")
    if not isinstance(type_annotation, type):
        raise raise_type(
            f"The annotation for {name} must be a type, got {type_annotation} of type {type(type_annotation)}."
        )
    return type_annotation


PUBLIC_RULE_DECORATOR_ARGUMENTS = {"canonical_name", "desc", "level"}
# We don't want @rule-writers to use 'rule_type' or 'cacheable' as kwargs directly,
# but rather set them implicitly based on the rule annotation.
# So we leave it out of PUBLIC_RULE_DECORATOR_ARGUMENTS.
IMPLICIT_PRIVATE_RULE_DECORATOR_ARGUMENTS = {"rule_type", "cacheable"}


def rule_decorator(func, **kwargs) -> Callable:
    if not inspect.isfunction(func):
        raise ValueError("The @rule decorator expects to be placed on a function.")

    if (
        len(
            set(kwargs)
            - PUBLIC_RULE_DECORATOR_ARGUMENTS
            - IMPLICIT_PRIVATE_RULE_DECORATOR_ARGUMENTS
        )
        != 0
    ):
        raise UnrecognizedRuleArgument(
            f"`@rule`s and `@goal_rule`s only accept the following keyword arguments: {PUBLIC_RULE_DECORATOR_ARGUMENTS}"
        )

    rule_type: RuleType = kwargs["rule_type"]
    cacheable: bool = kwargs["cacheable"]

    func_id = f"@rule {func.__module__}:{func.__name__}"
    type_hints = get_type_hints(func)
    return_type = _ensure_type_annotation(
        type_annotation=type_hints.get("return"),
        name=f"{func_id} return",
        raise_type=MissingReturnTypeAnnotation,
    )
    parameter_types = tuple(
        _ensure_type_annotation(
            type_annotation=type_hints.get(parameter),
            name=f"{func_id} parameter {parameter}",
            raise_type=MissingParameterTypeAnnotation,
        )
        for parameter in inspect.signature(func).parameters
    )
    is_goal_cls = issubclass(return_type, Goal)
    validate_parameter_types(func_id, parameter_types, cacheable)

    # Set a default canonical name if one is not explicitly provided to the module and name of the
    # function that implements it. This is used as the workunit name.
    effective_name = kwargs.get("canonical_name", f"{func.__module__}.{func.__name__}")

    # Set a default description, which is used in the dynamic UI and stacktraces.
    effective_desc = kwargs.get("desc")
    if effective_desc is None and is_goal_cls:
        effective_desc = f"`{return_type.name}` goal"

    effective_level = kwargs.get("level", LogLevel.TRACE)
    if not isinstance(effective_level, LogLevel):
        raise ValueError(
            "Expected to receive a value of type LogLevel for the level "
            f"argument, but got: {effective_level}"
        )

    return _make_rule(
        rule_type,
        return_type,
        parameter_types,
        cacheable=cacheable,
        canonical_name=effective_name,
        desc=effective_desc,
        level=effective_level,
    )(func)


def validate_parameter_types(
    func_id: str, parameter_types: Tuple[Type, ...], cacheable: bool
) -> None:
    if cacheable:
        for ty in parameter_types:
            if side_effecting.is_instance(ty):
                # TODO: Technically this will also fire for an @_uncacheable_rule, but we don't
                #  expose those as part of the API, so it's OK for this error not to mention them.
                raise ValueError(
                    f"A `@rule` that was not a @goal_rule ({func_id}) has a side-effecting parameter: {ty}"
                )


def inner_rule(*args, **kwargs) -> Callable:
    if len(args) == 1 and inspect.isfunction(args[0]):
        return rule_decorator(*args, **kwargs)
    else:

        def wrapper(*args):
            return rule_decorator(*args, **kwargs)

        return wrapper


def rule(*args, **kwargs) -> Callable:
    return inner_rule(*args, **kwargs, rule_type=RuleType.rule, cacheable=True)


def goal_rule(*args, **kwargs) -> Callable:
    if "level" not in kwargs:
        kwargs["level"] = LogLevel.DEBUG
    return inner_rule(*args, **kwargs, rule_type=RuleType.goal_rule, cacheable=False)


# This has a "private" name, as we don't (yet?) want it to be part of the rule API, at least
# until we figure out the implications, and have a handle on the semantics and use-cases.
def _uncacheable_rule(*args, **kwargs) -> Callable:
    return inner_rule(*args, **kwargs, rule_type=RuleType.uncacheable_rule, cacheable=False)


class Rule(ABC):
    """Rules declare how to produce products for the product graph.

    A rule describes what dependencies must be provided to produce a particular product. They also
    act as factories for constructing the nodes within the graph.
    """

    @property
    @abstractmethod
    def output_type(self):
        """An output `type` for the rule."""


def collect_rules(*namespaces: Union[ModuleType, Mapping[str, Any]]) -> Iterable[Rule]:
    """Collects all @rules in the given namespaces.

    If no namespaces are given, collects all the @rules in the caller's module namespace.
    """
    if not namespaces:
        currentframe = inspect.currentframe()
        assert isinstance(currentframe, FrameType)
        caller_frame = currentframe.f_back
        caller_module = inspect.getmodule(caller_frame)
        assert isinstance(caller_module, ModuleType)
        namespaces = (caller_module,)

    def iter_rules():
        for namespace in namespaces:
            mapping = namespace.__dict__ if isinstance(namespace, ModuleType) else namespace
            for name, item in mapping.items():
                if not callable(item):
                    continue
                rule = getattr(item, "rule", None)
                if isinstance(rule, TaskRule):
                    for input in rule.input_selectors:
                        if issubclass(input, OptionableFactory):
                            yield SubsystemRule(input)
                    if issubclass(rule.output_type, Goal):
                        yield SubsystemRule(rule.output_type.subsystem_cls)
                    yield rule

    return list(iter_rules())


@frozen_after_init
@dataclass(unsafe_hash=True)
class TaskRule(Rule):
    """A Rule that runs a task function when all of its input selectors are satisfied.

    NB: This API is not meant for direct consumption. To create a `TaskRule` you should always
    prefer the `@rule` constructor.
    """

    _output_type: Type
    input_selectors: Tuple[Type, ...]
    input_gets: Tuple[GetConstraints, ...]
    func: Callable
    cacheable: bool
    canonical_name: str
    desc: Optional[str]
    level: LogLevel

    def __init__(
        self,
        output_type: Type,
        input_selectors: Iterable[Type],
        func: Callable,
        input_gets: Iterable[GetConstraints],
        canonical_name: str,
        desc: Optional[str] = None,
        level: LogLevel = LogLevel.TRACE,
        cacheable: bool = True,
    ) -> None:
        self._output_type = output_type
        self.input_selectors = tuple(input_selectors)
        self.input_gets = tuple(input_gets)
        self.func = func  # type: ignore[assignment] # cannot assign to a method
        self.cacheable = cacheable
        self.canonical_name = canonical_name
        self.desc = desc
        self.level = level

    def __str__(self):
        return "(name={}, {}, {!r}, {}, gets={})".format(
            getattr(self, "name", "<not defined>"),
            self.output_type.__name__,
            self.input_selectors,
            self.func.__name__,
            self.input_gets,
        )

    @property
    def output_type(self):
        return self._output_type


@frozen_after_init
@dataclass(unsafe_hash=True)
class QueryRule(Rule):
    """A QueryRule declares that a given set of Params will be used to request an output type.

    Every callsite to `Scheduler.product_request` should have a corresponding QueryRule to ensure
    that the relevant portions of the RuleGraph are generated.
    """

    _output_type: Type
    input_types: Tuple[Type, ...]

    def __init__(self, output_type: Type, input_types: Sequence[Type]) -> None:
        self._output_type = output_type
        self.input_types = tuple(input_types)

    @property
    def output_type(self):
        return self._output_type


@dataclass(frozen=True)
class RuleIndex:
    """Holds a normalized index of Rules used to instantiate Nodes."""

    rules: FrozenOrderedSet[TaskRule]
    queries: FrozenOrderedSet[QueryRule]
    union_rules: FrozenOrderedSet[UnionRule]

    @classmethod
    def create(cls, rule_entries: Iterable[Rule]) -> RuleIndex:
        """Creates a RuleIndex with tasks indexed by their output type."""
        rules: OrderedSet[TaskRule] = OrderedSet()
        queries: OrderedSet[QueryRule] = OrderedSet()
        union_rules: OrderedSet[UnionRule] = OrderedSet()

        for entry in rule_entries:
            if isinstance(entry, TaskRule):
                rules.add(entry)
            elif isinstance(entry, UnionRule):
                union_rules.add(entry)
            elif isinstance(entry, QueryRule):
                queries.add(entry)
            elif hasattr(entry, "__call__"):
                rule = getattr(entry, "rule", None)
                if rule is None:
                    raise TypeError(f"Expected function {entry} to be decorated with @rule.")
                rules.add(rule)
            else:
                raise TypeError(
                    f"Rule entry {entry} had an unexpected type: {type(entry)}. Rules either "
                    "extend Rule or UnionRule, or are static functions decorated with @rule."
                )

        return RuleIndex(
            rules=FrozenOrderedSet(rules),
            queries=FrozenOrderedSet(queries),
            union_rules=FrozenOrderedSet(union_rules),
        )
