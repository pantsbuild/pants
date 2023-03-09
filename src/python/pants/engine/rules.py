# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass
from enum import Enum
from types import FrameType, ModuleType
from typing import (
    Any,
    Callable,
    Iterable,
    Mapping,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    get_type_hints,
    overload,
)

from typing_extensions import ParamSpec, Protocol

from pants.base.deprecated import deprecated, warn_or_error
from pants.engine.engine_aware import SideEffecting
from pants.engine.goal import Goal
from pants.engine.internals.rule_visitor import collect_awaitables
from pants.engine.internals.selectors import AwaitableConstraints
from pants.engine.internals.selectors import Effect as Effect  # noqa: F401
from pants.engine.internals.selectors import Get as Get  # noqa: F401
from pants.engine.internals.selectors import MultiGet as MultiGet  # noqa: F401
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.memo import memoized
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import softwrap

PANTS_RULES_MODULE_KEY = "__pants_rules__"


# NB: This violates Python naming conventions of using snake_case for functions. This is because
# SubsystemRule behaves very similarly to UnionRule and RootRule, and we want to use the same
# naming scheme.
#
# We could refactor this to be a class with __call__() defined, but we would lose the `@memoized`
# decorator.
@memoized
def SubsystemRule(subsystem: Type[Subsystem]) -> Rule:
    """Returns a TaskRule that constructs an instance of the subsystem."""
    warn_or_error(
        removal_version="2.17.0.dev0",
        entity=f"using `SubsystemRule({subsystem.__name__})`",
        hint=f"Use `*{subsystem.__name__}.rules()` instead.",
    )
    return next(iter(subsystem.rules()))  # type: ignore[call-arg]  # mypy dislikes memoziedclassmethod


class RuleType(Enum):
    rule = "rule"
    goal_rule = "goal_rule"
    uncacheable_rule = "_uncacheable_rule"


def _make_rule(
    func_id: str,
    rule_type: RuleType,
    return_type: Type,
    parameter_types: Iterable[Type],
    masked_types: Iterable[Type],
    *,
    cacheable: bool,
    canonical_name: str,
    desc: Optional[str],
    level: LogLevel,
) -> Callable[[Callable], Callable]:
    """A @decorator that declares that a particular static function may be used as a TaskRule.

    :param rule_type: The specific decorator used to declare the rule.
    :param return_type: The return/output type for the Rule. This must be a concrete Python type.
    :param parameter_types: A sequence of types that matches the number and order of arguments to
                            the decorated function.
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

        awaitables = FrozenOrderedSet(collect_awaitables(func))

        validate_requirements(func_id, parameter_types, awaitables, cacheable)

        # Set our own custom `__line_number__` dunder so that the engine may visualize the line number.
        func.__line_number__ = func.__code__.co_firstlineno

        func.rule = TaskRule(
            return_type,
            parameter_types,
            awaitables,
            masked_types,
            func,
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


class DuplicateRuleError(TypeError):
    """Invalid to overwrite `@rule`s using the same name in the same module."""


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
# We aren't sure if these'll stick around or be removed at some point, so they are "private"
# and should only be used in Pants' codebase.
PRIVATE_RULE_DECORATOR_ARGUMENTS = {
    # Allows callers to override the type Pants will use for the params listed.
    #
    # It is assumed (but not enforced) that the provided type is a subclass of the annotated type.
    # (We assume but not enforce since this is likely to be used with unions, which has the same
    # assumption between the union base and its members).
    "_param_type_overrides",
    # Allows callers to prevent the given list of types from being included in the identity of
    # a @rule. Although the type may be in scope for callers, it will not be consumable in the
    # `@rule` which declares the type masked.
    "_masked_types",
}
# We don't want @rule-writers to use 'rule_type' or 'cacheable' as kwargs directly,
# but rather set them implicitly based on the rule annotation.
# So we leave it out of PUBLIC_RULE_DECORATOR_ARGUMENTS.
IMPLICIT_PRIVATE_RULE_DECORATOR_ARGUMENTS = {"rule_type", "cacheable"}


def rule_decorator(func, **kwargs) -> Callable:
    if not inspect.isfunction(func):
        raise ValueError("The @rule decorator expects to be placed on a function.")

    if hasattr(func, "rule_helper"):
        raise ValueError("Cannot use both @rule and @rule_helper")

    if (
        len(
            set(kwargs)
            - PUBLIC_RULE_DECORATOR_ARGUMENTS
            - PRIVATE_RULE_DECORATOR_ARGUMENTS
            - IMPLICIT_PRIVATE_RULE_DECORATOR_ARGUMENTS
        )
        != 0
    ):
        raise UnrecognizedRuleArgument(
            f"`@rule`s and `@goal_rule`s only accept the following keyword arguments: {PUBLIC_RULE_DECORATOR_ARGUMENTS}"
        )

    rule_type: RuleType = kwargs["rule_type"]
    cacheable: bool = kwargs["cacheable"]
    masked_types: tuple[type, ...] = tuple(kwargs.get("_masked_types", ()))
    param_type_overrides: dict[str, type] = kwargs.get("_param_type_overrides", {})

    func_id = f"@rule {func.__module__}:{func.__name__}"
    type_hints = get_type_hints(func)
    return_type = _ensure_type_annotation(
        type_annotation=type_hints.get("return"),
        name=f"{func_id} return",
        raise_type=MissingReturnTypeAnnotation,
    )

    func_params = inspect.signature(func).parameters
    for parameter in param_type_overrides:
        if parameter not in func_params:
            raise ValueError(
                f"Unknown parameter name in `param_type_overrides`: {parameter}."
                + f" Parameter names: '{', '.join(func_params)}'"
            )

    parameter_types = tuple(
        _ensure_type_annotation(
            type_annotation=param_type_overrides.get(parameter, type_hints.get(parameter)),
            name=f"{func_id} parameter {parameter}",
            raise_type=MissingParameterTypeAnnotation,
        )
        for parameter in func_params
    )
    is_goal_cls = issubclass(return_type, Goal)

    # Set a default canonical name if one is not explicitly provided to the module and name of the
    # function that implements it. This is used as the workunit name.
    effective_name = kwargs.get(
        "canonical_name", f"{func.__module__}.{func.__qualname__}".replace(".<locals>", "")
    )

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

    module = sys.modules[func.__module__]
    pants_rules = getattr(module, PANTS_RULES_MODULE_KEY, None)
    if pants_rules is None:
        pants_rules = {}
        setattr(module, PANTS_RULES_MODULE_KEY, pants_rules)

    if effective_name not in pants_rules:
        pants_rules[effective_name] = func
    else:
        prev_func = pants_rules[effective_name]
        if prev_func.__code__ != func.__code__:
            raise DuplicateRuleError(
                softwrap(
                    f"""
                    Redeclaring rule {effective_name} with {func} at line
                    {func.__code__.co_firstlineno}, previously defined by {prev_func} at line
                    {prev_func.__code__.co_firstlineno}.
                    """
                )
            )

    return _make_rule(
        func_id,
        rule_type,
        return_type,
        parameter_types,
        masked_types,
        cacheable=cacheable,
        canonical_name=effective_name,
        desc=effective_desc,
        level=effective_level,
    )(func)


def validate_requirements(
    func_id: str,
    parameter_types: Tuple[Type, ...],
    awaitables: Tuple[AwaitableConstraints, ...],
    cacheable: bool,
) -> None:
    # TODO: Technically this will also fire for an @_uncacheable_rule, but we don't expose those as
    # part of the API, so it's OK for these errors not to mention them.
    for ty in parameter_types:
        if cacheable and issubclass(ty, SideEffecting):
            raise ValueError(
                f"A `@rule` that is not a @goal_rule ({func_id}) may not have "
                f"a side-effecting parameter: {ty}."
            )
    for awaitable in awaitables:
        input_type_side_effecting = [
            it for it in awaitable.input_types if issubclass(it, SideEffecting)
        ]
        if input_type_side_effecting and not awaitable.is_effect:
            raise ValueError(
                f"A `Get` may not request side-effecting types ({input_type_side_effecting}). "
                f"Use `Effect` instead: `{awaitable}`."
            )
        if not input_type_side_effecting and awaitable.is_effect:
            raise ValueError(
                f"An `Effect` should not be used with pure types ({awaitable.input_types}). "
                f"Use `Get` instead: `{awaitable}`."
            )
        if cacheable and awaitable.is_effect:
            raise ValueError(
                f"A `@rule` that is not a @goal_rule ({func_id}) may not use an "
                f"Effect: `{awaitable}`."
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


P = ParamSpec("P")
R = TypeVar("R")


def _rule_helper_decorator(func: Callable[P, R], _public: bool = False) -> Callable[P, R]:
    if not _public and not func.__name__.startswith("_"):
        raise ValueError("@rule_helpers must be private. I.e. start with an underscore.")

    if hasattr(func, "rule"):
        raise ValueError("Cannot use both @rule and @rule_helper.")

    if not inspect.iscoroutinefunction(func):
        raise ValueError("@rule_helpers must be async.")

    setattr(func, "rule_helper", func)
    return func  # type: ignore[return-value]


@overload
def rule_helper(func: Callable[P, R]) -> Callable[P, R]:
    ...


@overload
def rule_helper(func: None = None, **kwargs: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
    ...


@deprecated(
    removal_version="2.20.0.dev0",
    hint=softwrap(
        """
        The `@rule_helper` decorator is no longer needed. `@rule` methods may call any other
        methods, and if they are `async` may also use `Get` and `MultiGet`.
        """
    ),
)
def rule_helper(
    func: Callable[P, R] | None = None, **kwargs: Any
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator which marks a function as a "rule helper".

    This docstring is now deprecated. Any async method may now use `await Get/MultiGet`.

    Functions marked as rule helpers are allowed to be called by rules and other rule helpers
    and can `await Get/MultiGet`. The rule parser adds these functions' awaitables to the rule's
    awaitables.

    There are a few restrictions:
        1. Rule helpers must be "private". I.e. start with an underscore.
        2. Rule hlpers must be `async`
        3. Rule helpers can't be rules
        4. Rule helpers must be accessed by attributes chained from a module variable (see below)

    To explain restriction 4, consider the following:
    ```
        from some_mod import helper_function, attribute

        ...

        some_instance = AClass()

        @rule
        async def my_rule(arg: RequestType) -> ReturnType
            await helper_function()  # OK
            await attribute.helper()  # OK (assuming `helper` is a @rule_helper)
            await attribute.otherattr.helper()  # OK (assuming `helper` is a @rule_helper)
            await some_instance.helper()  # OK (assuming `helper` is a @rule_helper)

            await AClass().helper()  # Not OK, won't collect awaitables from `helper`

            func_var = AClass()
            await func_var.helper()  # Not OK, won't collect awaitables from `helper`
            await arg.helper()  # Not OK, won't collect awaitables from `helper`
    ```
    """
    if func is None:

        def wrapper(func: Callable[P, R]) -> Callable[P, R]:
            return _rule_helper_decorator(func, **kwargs)

        return wrapper

    return _rule_helper_decorator(func, **kwargs)


class Rule(Protocol):
    """Rules declare how to produce products for the product graph.

    A rule describes what dependencies must be provided to produce a particular product. They also
    act as factories for constructing the nodes within the graph.
    """

    @property
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
        assert isinstance(caller_frame, FrameType)

        global_items = caller_frame.f_globals
        namespaces = (global_items,)

    def iter_rules():
        for namespace in namespaces:
            mapping = namespace.__dict__ if isinstance(namespace, ModuleType) else namespace
            for item in mapping.values():
                if not callable(item):
                    continue
                rule = getattr(item, "rule", None)
                if isinstance(rule, TaskRule):
                    for input in rule.input_selectors:
                        if issubclass(input, Subsystem):
                            yield from input.rules()
                        if issubclass(input, Subsystem.EnvironmentAware):
                            yield from input.subsystem.rules()
                    if issubclass(rule.output_type, Goal):
                        yield from rule.output_type.subsystem_cls.rules()
                    yield rule

    return list(iter_rules())


@dataclass(frozen=True)
class TaskRule:
    """A Rule that runs a task function when all of its input selectors are satisfied.

    NB: This API is not meant for direct consumption. To create a `TaskRule` you should always
    prefer the `@rule` constructor.
    """

    output_type: Type
    input_selectors: Tuple[Type, ...]
    input_gets: Tuple[AwaitableConstraints, ...]
    masked_types: Tuple[Type, ...]
    func: Callable
    canonical_name: str
    desc: Optional[str] = None
    level: LogLevel = LogLevel.TRACE
    cacheable: bool = True

    def __str__(self):
        return "(name={}, {}, {!r}, {}, gets={})".format(
            getattr(self, "name", "<not defined>"),
            self.output_type.__name__,
            self.input_selectors,
            self.func.__name__,
            self.input_gets,
        )


@dataclass(frozen=True)
class QueryRule:
    """A QueryRule declares that a given set of Params will be used to request an output type.

    Every callsite to `Scheduler.product_request` should have a corresponding QueryRule to ensure
    that the relevant portions of the RuleGraph are generated.
    """

    output_type: Type
    input_types: Tuple[Type, ...]

    def __init__(self, output_type: Type, input_types: Iterable[Type]) -> None:
        object.__setattr__(self, "output_type", output_type)
        object.__setattr__(self, "input_types", tuple(input_types))


@dataclass(frozen=True)
class RuleIndex:
    """Holds a normalized index of Rules used to instantiate Nodes."""

    rules: FrozenOrderedSet[TaskRule]
    queries: FrozenOrderedSet[QueryRule]
    union_rules: FrozenOrderedSet[UnionRule]

    @classmethod
    def create(cls, rule_entries: Iterable[Rule | UnionRule]) -> RuleIndex:
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
