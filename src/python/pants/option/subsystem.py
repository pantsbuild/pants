# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import inspect
import re
from abc import ABCMeta
from typing import Any, Callable, ClassVar, Generic, TypeVar, overload

from pants.engine.internals.selectors import AwaitableConstraints, Get
from pants.option.errors import OptionsError
from pants.option.option_value_container import OptionValueContainer
from pants.option.scope import Scope, ScopedOptions, ScopeInfo, normalize_scope


class Subsystem(metaclass=ABCMeta):
    """A separable piece of functionality that may be reused across multiple tasks or other code.

    Subsystems encapsulate the configuration and initialization of things like JVMs,
    Python interpreters, SCMs and so on.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.
    """

    options_scope: str
    help: ClassVar[str]

    # Subclasses may override these to specify a deprecated former name for this Subsystem's scope.
    # Option values can be read from the deprecated scope, but a deprecation warning will be issued.
    # The deprecation warning becomes an error at the given Pants version (which must therefore be
    # a valid semver).
    deprecated_options_scope: str | None = None
    deprecated_options_scope_removal_version: str | None = None

    _scope_name_re = re.compile(r"^(?:[a-z0-9_])+(?:-(?:[a-z0-9_])+)*$")

    @classmethod
    def signature(cls):
        """Returns kwargs to construct a `TaskRule` that will construct the target Subsystem.

        TODO: This indirection avoids a cycle between this module and the `rules` module.
        """
        partial_construct_subsystem = functools.partial(_construct_subsytem, cls)

        # NB: We must populate several dunder methods on the partial function because partial
        # functions do not have these defined by default and the engine uses these values to
        # visualize functions in error messages and the rule graph.
        snake_scope = normalize_scope(cls.options_scope)
        name = f"construct_scope_{snake_scope}"
        partial_construct_subsystem.__name__ = name
        partial_construct_subsystem.__module__ = cls.__module__
        partial_construct_subsystem.__doc__ = cls.help
        _, class_definition_lineno = inspect.getsourcelines(cls)
        partial_construct_subsystem.__line_number__ = class_definition_lineno

        return dict(
            output_type=cls,
            input_selectors=(),
            func=partial_construct_subsystem,
            input_gets=(
                AwaitableConstraints(output_type=ScopedOptions, input_type=Scope, is_effect=False),
            ),
            canonical_name=name,
        )

    @classmethod
    def is_valid_scope_name(cls, s: str) -> bool:
        return s == "" or cls._scope_name_re.match(s) is not None

    @classmethod
    def validate_scope(cls) -> None:
        options_scope = getattr(cls, "options_scope", None)
        if options_scope is None:
            raise OptionsError(f"{cls.__name__} must set options_scope.")
        if not cls.is_valid_scope_name(options_scope):
            raise OptionsError(
                f'Options scope "{options_scope}" is not valid:\nReplace in code with a new '
                "scope name consisting of only lower-case letters, digits, underscores, "
                "and non-consecutive dashes."
            )

    @classmethod
    def create_scope_info(cls, **scope_info_kwargs) -> ScopeInfo:
        """One place to create scope info, to allow subclasses to inject custom scope args."""
        return ScopeInfo(**scope_info_kwargs)

    @classmethod
    def get_scope_info(cls) -> ScopeInfo:
        """Returns a ScopeInfo instance representing this Subsystem's options scope."""
        cls.validate_scope()
        return cls.create_scope_info(scope=cls.options_scope, subsystem_cls=cls)

    @classmethod
    def register_options(cls, register):
        """Register options for this Subsystem.

        Subclasses may override and call register(*args, **kwargs).
        """
        for attrname in dir(cls):
            attr = getattr(cls, attrname)
            if isinstance(attr, Option):
                register(*attr.args, **attr.kwargs)

    @classmethod
    def register_options_on_scope(cls, options):
        """Trigger registration of this Subsystem's options.

        Subclasses should not generally need to override this method.
        """
        cls.register_options(options.registration_function_for_subsystem(cls))

    def __init__(self, options: OptionValueContainer) -> None:
        self.validate_scope()
        self.options = options

    def __eq__(self, other: Any) -> bool:
        if type(self) != type(other):
            return False
        return bool(self.options == other.options)


_SubsystemT = TypeVar("_SubsystemT", bound=Subsystem)
_T = TypeVar("_T")


class Option(Generic[_T]):
    """Data-descriptor for subsystem options.

    This class exists to help eliminate the repetition of declaring options in `register_options`
    and having to declare properties for mypy's sake.

    Usage:
        class Engine(Subsystem):
            ...

            cylinders = Option[int]("--cylinders", default=6, help="...")

        ...

        engine: Engine = ...
        engine.cylinders  # mypy knows this is an int

    Under-the-hood:
        - The `type` argument if omitted defaults to the type of `default`
        - You can pass a `converter` function to convert the option value into the property value
            E.g. `converter=tuple`
    """

    # NB: We have to ignore type because we can't `cast(_T, x)` as `_T` is purely a type-checking
    # construct and `cast()` is a runtime function.
    DEFAULT_CONVERTER: Callable[[Any], _T] = lambda x: x  # type: ignore

    def __init__(
        self,
        *args: str,
        converter: Callable[[Any], _T] = DEFAULT_CONVERTER,
        **kwargs: Any,
    ):
        self.args = args
        self.converter = converter
        if "type" not in kwargs:
            kwargs.setdefault("type", type(kwargs["default"]))
        self.kwargs = kwargs

    @overload
    def __get__(self, obj: None, *args: Any) -> Option:
        ...

    @overload
    def __get__(self, obj: _SubsystemT, *args: Any) -> _T:
        ...

    def __get__(self, obj: _SubsystemT | None, *args: Any) -> Option | _T:
        if obj is None:
            return self
        long_name = self.args[-1]
        option_value = getattr(obj.options, long_name[2:].replace("-", "_"))
        return self.converter(option_value)


async def _construct_subsytem(subsystem_typ: type[_SubsystemT]) -> _SubsystemT:
    scoped_options = await Get(ScopedOptions, Scope(str(subsystem_typ.options_scope)))
    return subsystem_typ(scoped_options.options)
