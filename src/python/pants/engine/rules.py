# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import inspect
import sys
from dataclasses import dataclass
from enum import Enum
from types import FrameType, ModuleType
from typing import (
    Any,
    Callable,
    Coroutine,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    get_type_hints,
    overload,
)

from typing_extensions import ParamSpec

from pants.engine.engine_aware import SideEffecting
from pants.engine.goal import Goal
from pants.engine.internals.rule_visitor import collect_awaitables
from pants.engine.internals.selectors import AwaitableConstraints, Call
from pants.engine.internals.selectors import Effect as Effect  # noqa: F401
from pants.engine.internals.selectors import Get as Get  # noqa: F401
from pants.engine.internals.selectors import MultiGet as MultiGet  # noqa: F401
from pants.engine.internals.selectors import concurrently as concurrently  # noqa: F401
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import softwrap

PANTS_RULES_MODULE_KEY = "__pants_rules__"


def implicitly(*args) -> dict[str, Any]:
    # NB: This function does not have a `TypedDict` return type, because the `@rule` decorator
    # cannot adjust the type of the `@rule` function to include a keyword argument (keyword
    # arguments are not supported by PEP-612).
    return {"__implicitly": args}


class RuleType(Enum):
    rule = "rule"
    goal_rule = "goal_rule"
    uncacheable_rule = "_uncacheable_rule"


P = ParamSpec("P")
R = TypeVar("R")
SyncRuleT = Callable[P, R]
AsyncRuleT = Callable[P, Coroutine[Any, Any, R]]
RuleDecorator = Callable[[Union[SyncRuleT, AsyncRuleT]], AsyncRuleT]


def _rule_call_trampoline(rule_id: str, output_type: type, func: Callable[P, R]) -> Callable[P, R]:
    @functools.wraps(func)  # type: ignore
    async def wrapper(*args, __implicitly: Sequence[Any] = (), **kwargs):
        call = Call(rule_id, output_type, args, *__implicitly)  # type: ignore[call-overload]
        return await call

    return cast(Callable[P, R], wrapper)


def _make_rule(
    func_id: str,
    rule_type: RuleType,
    return_type: Type,
    parameter_types: dict[str, Type],
    masked_types: Iterable[Type],
    *,
    cacheable: bool,
    canonical_name: str,
    desc: Optional[str],
    level: LogLevel,
) -> RuleDecorator:
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

    def wrapper(original_func):
        if not inspect.isfunction(original_func):
            raise ValueError("The @rule decorator must be applied innermost of all decorators.")

        awaitables = FrozenOrderedSet(collect_awaitables(original_func))

        validate_requirements(func_id, parameter_types, awaitables, cacheable)

        # Set our own custom `__line_number__` dunder so that the engine may visualize the line number.
        original_func.__line_number__ = original_func.__code__.co_firstlineno

        func = _rule_call_trampoline(canonical_name, return_type, original_func)

        # NB: The named definition of the rule ends up wrapped in a trampoline to handle memoization
        # and implicit arguments for direct by-name calls. But the `TaskRule` takes a reference to
        # the original unwrapped function, which avoids the need for a special protocol when the
        # engine invokes a @rule under memoization.
        func.rule = TaskRule(
            return_type,
            FrozenDict(parameter_types),
            awaitables,
            masked_types,
            original_func,
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


PUBLIC_RULE_DECORATOR_ARGUMENTS = {"canonical_name", "canonical_name_suffix", "desc", "level"}
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


def rule_decorator(func: SyncRuleT | AsyncRuleT, **kwargs) -> AsyncRuleT:
    if not inspect.isfunction(func):
        raise ValueError("The @rule decorator expects to be placed on a function.")

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

    parameter_types = {
        parameter: _ensure_type_annotation(
            type_annotation=param_type_overrides.get(parameter, type_hints.get(parameter)),
            name=f"{func_id} parameter {parameter}",
            raise_type=MissingParameterTypeAnnotation,
        )
        for parameter in func_params
    }
    is_goal_cls = issubclass(return_type, Goal)

    # Set a default canonical name if one is not explicitly provided to the module and name of the
    # function that implements it, plus an optional suffix. This is used as the workunit name.
    # The suffix is a convenient way to disambiguate multiple rules registered dynamically from the
    # same static code (by overriding the inferred param types in the @rule decorator).
    # TODO: It is not yet clear how dynamically registered rules whose names are generated
    #  with a suffix will work in practice with the new call-by-name semantics.
    #  For now the suffix serves to ensure unique names. Whether they are useful is another matter.
    suffix = kwargs.get("canonical_name_suffix", "")
    effective_name = kwargs.get(
        "canonical_name",
        f"{func.__module__}.{func.__qualname__}{('_' + suffix) if suffix else ''}".replace(
            ".<locals>", ""
        ),
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
    parameter_types: dict[str, Type],
    awaitables: Tuple[AwaitableConstraints, ...],
    cacheable: bool,
) -> None:
    # TODO: Technically this will also fire for an @_uncacheable_rule, but we don't expose those as
    # part of the API, so it's OK for these errors not to mention them.
    for ty in parameter_types.values():
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


def inner_rule(*args, **kwargs) -> AsyncRuleT | RuleDecorator:
    if len(args) == 1 and inspect.isfunction(args[0]):
        return rule_decorator(*args, **kwargs)
    else:

        def wrapper(*args):
            return rule_decorator(*args, **kwargs)

        return wrapper


@overload
def rule(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]: ...


@overload
def rule(func: Callable[P, R]) -> Callable[P, Coroutine[Any, Any, R]]: ...


@overload
def rule(
    *args, func: None = None, **kwargs: Any
) -> Callable[[Union[SyncRuleT, AsyncRuleT]], AsyncRuleT]: ...


def rule(*args, **kwargs):
    return inner_rule(*args, **kwargs, rule_type=RuleType.rule, cacheable=True)


@overload
def goal_rule(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]: ...


@overload
def goal_rule(func: Callable[P, R]) -> Callable[P, Coroutine[Any, Any, R]]: ...


@overload
def goal_rule(
    *args, func: None = None, **kwargs: Any
) -> Callable[[Union[SyncRuleT, AsyncRuleT]], AsyncRuleT]: ...


def goal_rule(*args, **kwargs):
    if "level" not in kwargs:
        kwargs["level"] = LogLevel.DEBUG
    return inner_rule(*args, **kwargs, rule_type=RuleType.goal_rule, cacheable=False)


# This has a "private" name, as we don't (yet?) want it to be part of the rule API, at least
# until we figure out the implications, and have a handle on the semantics and use-cases.
def _uncacheable_rule(*args, **kwargs) -> AsyncRuleT | RuleDecorator:
    return inner_rule(*args, **kwargs, rule_type=RuleType.uncacheable_rule, cacheable=False)


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
                    for input in rule.parameters.values():
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
    parameters: FrozenDict[str, Type]
    awaitables: Tuple[AwaitableConstraints, ...]
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
            self.parameters.values(),
            self.func.__name__,
            self.awaitables,
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
