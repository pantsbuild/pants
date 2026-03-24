# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial, wraps
from types import GenericAlias
from typing import Any, Iterable, Self, Tuple, TypeVar, cast

from pants.engine.internals.native_engine import PyNgOptions, PyNgOptionsReader, PyOptionId
from pants.engine.rules import Rule, TaskRule, collect_rules, rule
from pants.ng.source_partition import SourcePartition
from pants.option.ranked_value import Rank
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_classmethod

# Supported option value types.
#
# Note that this is a subset of the value types supported by og Pants, which allows
# nested and heterogenously-valued dicts. However that doesn't seem to be worth the effort
# so let's see how far we can get without supporting those. Note also that these types are all
# immutable, whereas the og types did not have to be. Again, not a complication we should
# be enthusiastic to support.
ScalarValue = bool | str | int | float
OptionValue = ScalarValue | tuple[ScalarValue, ...] | FrozenDict[str, str]


_SCALAR_TYPES = typing.get_args(ScalarValue)


def _is_valid_type(t: type | GenericAlias) -> bool:
    if isinstance(t, type):
        # ScalarType
        return t in _SCALAR_TYPES

    torig = typing.get_origin(t)
    targs = typing.get_args(t)
    return (
        # tuple[ScalarType, ...]
        torig == tuple and len(targs) == 2 and targs[0] in _SCALAR_TYPES and targs[1] == Ellipsis
    ) or (
        # FrozenDict[str, str]
        torig == FrozenDict and targs == (str, str)
    )


def _type_to_readable_str(t: type | GenericAlias) -> str:
    if isinstance(t, type):
        # E.g., `str` instead of `<class 'str'>`
        return t.__name__
    # A GenericAlias renders as you'd expect (e.g., `tuple[str, ...]`).
    return str(t)


def _is_of_type(val: OptionValue, expected_type: type | GenericAlias) -> bool:
    if isinstance(expected_type, type) and expected_type in _SCALAR_TYPES:
        return isinstance(val, expected_type)

    torig = typing.get_origin(expected_type)
    targs = typing.get_args(expected_type)
    if torig == tuple:
        member_type = targs[0]
        return isinstance(val, tuple) and all(isinstance(member, member_type) for member in val)
    if torig == FrozenDict:
        return isinstance(val, FrozenDict) and all(
            (type(k), type(v)) == (str, str) for k, v in val.items()
        )
    # Should never happen, assuming we've already passed _is_valid_type().
    raise ValueError(f"Unexpected expected_type {expected_type}")


def _getter(getter: Callable, option_parser, option_id, default) -> tuple[Any, bool]:
    # The legacy getter returns a tuple of (value, rank, optional derivation),
    # we only care about value and rank.
    value, rank, _ = getter(option_parser, option_id, default)
    return value, rank > Rank.HARDCODED._rank


def _tuple_getter(
    getter: Callable, option_parser, option_id, default
) -> tuple[tuple[ScalarValue, ...], bool]:
    # The legacy getter returns a tuple of (list value, rank, optional derivation),
    # we only care about value and rank, and we convert the value to tuple. The rust code can
    # consume a tuple where a list is expected, so no need to convert the default.
    value, rank, _ = getter(option_parser, option_id, default or ())
    return tuple(value), rank > Rank.HARDCODED._rank


def _dict_getter(option_parser, option_id, default) -> tuple[FrozenDict, bool]:
    # The legacy getter returns a tuple of (value, rank, optional derivation),
    # we only care about value and rank, and we convert the value to FrozenDict.
    # We also convert the default to regular dict, so the Rust code can consume it.
    # The type checker currently doesn't grok the overloaded FrozenDict.__init__, so
    # we ignore the arg-type error.
    value, rank, _ = PyNgOptionsReader.get_dict(option_parser, option_id, dict(default or {}))
    return FrozenDict(value), rank > Rank.HARDCODED._rank  # type: ignore[arg-type]


# A map from type to getter for that type.
# Each getter is called with the arguments (options_reader, option_id, default) and
# returns a pair (value, is_explicit). is_explicit is True if the value was specified
# explicitly (by config, env var or flag), and False if the default was used.
# Note that this differentiates between the case of "no explicit value" vs "explicit value
# was provided, but it happened to be the same as the default value".
_getters: dict[type | GenericAlias, Callable] = {
    bool: partial(_getter, PyNgOptionsReader.get_bool),
    str: partial(_getter, PyNgOptionsReader.get_string),
    int: partial(_getter, PyNgOptionsReader.get_int),
    float: partial(_getter, PyNgOptionsReader.get_float),
    tuple[bool, ...]: partial(_tuple_getter, PyNgOptionsReader.get_bool_list),
    tuple[str, ...]: partial(_tuple_getter, PyNgOptionsReader.get_string_list),
    tuple[int, ...]: partial(_tuple_getter, PyNgOptionsReader.get_int_list),
    tuple[float, ...]: partial(_tuple_getter, PyNgOptionsReader.get_float_list),
    FrozenDict[str, str]: _dict_getter,
}


@dataclass(frozen=True)
class OptionDescriptor:
    """Information we capture at @option evaluation time."""

    name: str
    type: type | GenericAlias
    default: OptionValue | None
    help: str
    required: bool = False


R = TypeVar("R")
S = TypeVar("S")
OptionFunc = Callable[[S], R]
Default = OptionValue | Callable[[Any], OptionValue]
Help = str | Callable[[Any], str]


REQUIRED = object()


# A @decorator for options.
def option(*, help: Help, required: bool = False, default: Default | None = None) -> OptionFunc:
    def decorator(func: OptionFunc):
        # Mark the func as an option.
        func._option_ = True  # type: ignore[attr-defined]
        func._option_required_ = required  # type: ignore[attr-defined]
        func._option_default_ = default  # type: ignore[attr-defined]
        func._option_help_ = help  # type: ignore[attr-defined]

        @wraps(func)
        def wrapper(instance):
            return instance._option_values_[func.__name__]

        return property(wrapper)

    return decorator


class SubsystemNg:
    """A holder of options in a scope.

    Much lighter weight than its og counterpart.

    Use like this:

    class Foo(SubsystemNg):
        options_scope = "foo"

        @option(help="bar help")
        def bar(self) -> str: ...

        @option(default=42, help="baz help")
        def baz(self) -> int: ...

        ...

    The supported option types are: bool, str, int, float, tuple[bool, ...], tuple[str, ...],
    tuple[int, ...], tuple[float, ...] and FrozenDict[str, str].

    The `...` in the method bodies above are literal: the subsystem mechanism will provide the body.
    You may need `# mypy: disable-error-code=empty-body` for your code to pass mypy type checks, or
    you can use the mypy plugin at pants.ng.subsystem_mypy_plugin to suppress those errors.

    `default` and `help` can be values or callables that take the subsystem type as an arg, and
    return the relevant values.

    Subsystem instances are instantiated with a PyNgOptionsReader, and calling .bar or .baz (with
    no parentheses) on an instance of Foo will return the value of that option from the underlying
    parser.

    Option names must not _begin_and_end_ with an underscore. Such names are reserved for the
    underlying initialization mechanics.
    """

    _subsystem_ng_ = True

    # Subclasses must set.
    options_scope: str | None = None
    help: str | None = None

    # The ctor will set.
    _option_values_: FrozenDict[str, OptionValue] | None = None

    @classmethod
    def create(cls, options_reader: PyNgOptionsReader) -> Self:
        """Indirect constructor method.

        Useful for avoiding spurious mypy errors when instantiating instances in tests.
        """
        return cls(options_reader)

    def __init__(self, options_reader: PyNgOptionsReader):
        option_values = {}
        for descriptor in self._get_option_descriptors_():
            option_id = PyOptionId(descriptor.name, scope=self.options_scope)
            getter = _getters[descriptor.type]
            val, is_explicit = getter(
                options_reader, option_id=option_id, default=descriptor.default
            )
            if descriptor.required and not is_explicit:
                raise ValueError(
                    "No value provided for required option "
                    f"[{self.options_scope}].{descriptor.name}."
                )
            option_values[descriptor.name] = val
        self._option_values_ = FrozenDict(option_values)

    def _get_option_values_(self) -> FrozenDict[str, OptionValue]:
        return cast(FrozenDict[str, OptionValue], self._option_values_)

    def __str__(self) -> str:
        fields = [f"{k}={v}" for k, v in self._get_option_values_().items()]
        return f"{self.__class__.__name__}({', '.join(fields)})"

    @classmethod
    def _get_option_descriptors_(cls) -> tuple[OptionDescriptor, ...]:
        """Return the option descriptors for this subsystem.

        Must only be called after initialize() has been called.
        """
        return cast(tuple[OptionDescriptor], getattr(cls, "_option_descriptors_"))

    @classmethod
    def _initialize_(cls):
        if getattr(cls, "_option_descriptors_", None) is not None:
            return

        if cls.options_scope is None:
            raise ValueError(f"Subsystem class {cls.__name__} must set the options_scope classvar.")
        if cls.help is None:
            raise ValueError(f"Subsystem class {cls.__name__} must set the help classvar.")
        option_descriptors = []
        # We don't use dir() or inspect.getmembers() because those sort by name,
        # and we want to preserve declaration order.
        for basecls in inspect.getmro(cls):
            for name, member in basecls.__dict__.items():
                if not isinstance(member, property):
                    continue
                wrapped = member.fget
                if not getattr(wrapped, "_option_", False):
                    continue
                sig = inspect.signature(wrapped)
                if len(sig.parameters) != 1 or next(iter(sig.parameters)) != "self":
                    raise ValueError(
                        f"The @option decorator expects to be placed on a no-arg instance method, but {basecls.__name__}.{name} does not have this signature."
                    )
                option_type = sig.return_annotation
                if not _is_valid_type(option_type):
                    raise ValueError(
                        f"Invalid type `{option_type}` for option {basecls.__name__}.{name}"
                    )

                help = getattr(wrapped, "_option_help_")
                if callable(help):
                    help = help(cls)
                required = getattr(wrapped, "_option_required_")
                default = getattr(wrapped, "_option_default_")
                if required:
                    if default is not None:
                        raise ValueError(
                            "The option {basecls.__name__}.{name} is required, so it must not provide a default value."
                        )
                else:
                    if callable(default):
                        default = default(cls)
                    if default is not None and not _is_of_type(default, option_type):
                        raise ValueError(
                            f"The default for option {basecls.__name__}.{name} must be of type {_type_to_readable_str(option_type)} (or None)."
                        )
                option_descriptors.append(
                    OptionDescriptor(
                        name,
                        type=option_type,
                        required=required,
                        default=default,
                        help=help,
                    )
                )
        cls._option_descriptors_ = tuple(option_descriptors)

    @memoized_classmethod
    def _get_rules_(cls: Any) -> Iterable[Rule]:
        return cast(Iterable[Rule], (cls._construct_subsystem_rule_(),))

    @classmethod
    def _get_construct_func_(cls) -> Tuple[Callable, dict]:
        """Returns information that allows the engine to construct an instance of the subsystem.

        The return value is a pair (function, params) where the function takes the
        type of the subsystem as its first argument (`cls`) and the given params
        as its subsequent argument(s). The params dict is a map of param name -> param type.

        See below for examples of use (currently the only uses, in fact).
        """
        raise ValueError(f"_get_construct_func_() not implemented for {cls}")

    @classmethod
    def _construct_subsystem_rule_(cls) -> Rule:
        """Returns a `TaskRule` that will construct the target Subsystem."""
        construct_func, construct_func_params = cls._get_construct_func_()

        partial_construct_subsystem: Any = functools.partial(construct_func, cls)

        # NB: We populate several dunder methods on the partial function because partial
        # functions do not have these defined by default, and the engine uses these values to
        # visualize functions in error messages and the rule graph.
        name = f"construct_{cls.__name__}"
        partial_construct_subsystem.__name__ = name
        partial_construct_subsystem.__module__ = cls.__module__
        partial_construct_subsystem.__doc__ = cls.help() if callable(cls.help) else cls.help
        partial_construct_subsystem.__line_number__ = inspect.getsourcelines(cls)[1]

        return TaskRule(
            output_type=cls,
            parameters=FrozenDict(construct_func_params),
            awaitables=(),
            masked_types=(),
            func=partial_construct_subsystem,
            canonical_name=name,
        )


@dataclass(frozen=True)
class UniversalOptionsReader:
    options_reader: PyNgOptionsReader


@rule
async def get_universal_options_reader(options: PyNgOptions) -> UniversalOptionsReader:
    # The universal options are the options for the repo root dir.
    return UniversalOptionsReader(options.get_options_reader_for_dir(""))


class UniversalSubsystem(SubsystemNg):
    """A subsystem whose values are universal for all uses.

    Uses include:
    - Global options, as these affect the running of Pants itself.
    - Command/subcommand options, as these are typically provided on the command line and
      are intended by the user to apply to all sources.
    """

    @classmethod
    def _get_construct_func_(cls):
        return _construct_universal_subsystem, {"universal_options_reader": UniversalOptionsReader}


_UniversalSubsystemT = TypeVar("_UniversalSubsystemT", bound="UniversalSubsystem")


async def _construct_universal_subsystem(
    subsystem_typ: type[_UniversalSubsystemT],
    universal_options_reader: UniversalOptionsReader,
) -> _UniversalSubsystemT:
    return subsystem_typ(universal_options_reader.options_reader)


class ContextualSubsystem(SubsystemNg):
    """A subsystem whose values may vary depending on the sources it applies to.

    The main use is to allow config files in subdirectories to override option values
    set in parent directories (including the root directory), and for those overrides
    to apply just to the sources in or below those subdirectories.

    The input sources for a command will be partitioned into subsets, each attached to
    its own subsystem instance.
    """

    @classmethod
    def _get_construct_func_(cls):
        return _construct_contextual_subsystem, {"source_partition": SourcePartition}


_ContextualSubsystemT = TypeVar("_ContextualSubsystemT", bound="ContextualSubsystem")


async def _construct_contextual_subsystem(
    subsystem_typ: type[_ContextualSubsystemT],
    source_partition: SourcePartition,
) -> _ContextualSubsystemT:
    return subsystem_typ(source_partition.options_reader)


def rules() -> tuple[Rule, ...]:
    return tuple(collect_rules())
