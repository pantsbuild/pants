# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import inspect
import re
from abc import ABCMeta
from typing import Any, ClassVar, Optional, Type, TypeVar

from pants.engine.internals.selectors import Get, GetConstraints
from pants.option.errors import OptionsError
from pants.option.option_value_container import OptionValueContainer
from pants.option.scope import Scope, ScopedOptions, ScopeInfo


class Optionable(metaclass=ABCMeta):
    """A mixin for classes that can register options on some scope."""

    options_scope: str
    help: ClassVar[str]

    # Subclasses may override these to specify a deprecated former name for this Optionable's scope.
    # Option values can be read from the deprecated scope, but a deprecation warning will be issued.
    # The deprecation warning becomes an error at the given Pants version (which must therefore be
    # a valid semver).
    deprecated_options_scope: Optional[str] = None
    deprecated_options_scope_removal_version: Optional[str] = None

    _scope_name_component_re = re.compile(r"^(?:[a-z0-9_])+(?:-(?:[a-z0-9_])+)*$")

    @classmethod
    def signature(cls):
        """Returns kwargs to construct a `TaskRule` that will construct the target Optionable.

        TODO: This indirection avoids a cycle between this module and the `rules` module.
        """
        partial_construct_optionable = functools.partial(_construct_optionable, cls)

        # NB: We must populate several dunder methods on the partial function because partial
        # functions do not have these defined by default and the engine uses these values to
        # visualize functions in error messages and the rule graph.
        snake_scope = cls.options_scope.replace("-", "_")
        name = f"construct_scope_{snake_scope}"
        partial_construct_optionable.__name__ = name
        partial_construct_optionable.__module__ = cls.__module__
        _, class_definition_lineno = inspect.getsourcelines(cls)
        partial_construct_optionable.__line_number__ = class_definition_lineno

        return dict(
            output_type=cls,
            input_selectors=(),
            func=partial_construct_optionable,
            input_gets=(GetConstraints(output_type=ScopedOptions, input_type=Scope),),
            canonical_name=name,
        )

    @classmethod
    def is_valid_scope_name_component(cls, s: str) -> bool:
        return s == "" or cls._scope_name_component_re.match(s) is not None

    @classmethod
    def validate_scope(cls) -> None:
        options_scope = getattr(cls, "options_scope", None)
        if options_scope is None:
            raise OptionsError(f"{cls.__name__} must set options_scope.")
        if not cls.is_valid_scope_name_component(options_scope):
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
        """Returns a ScopeInfo instance representing this Optionable's options scope."""
        cls.validate_scope()
        return cls.create_scope_info(scope=cls.options_scope, optionable_cls=cls)

    @classmethod
    def register_options(cls, register):
        """Register options for this optionable.

        Subclasses may override and call register(*args, **kwargs).
        """

    @classmethod
    def register_options_on_scope(cls, options):
        """Trigger registration of this optionable's options.

        Subclasses should not generally need to override this method.
        """
        cls.register_options(options.registration_function_for_optionable(cls))

    def __init__(self, options: OptionValueContainer) -> None:
        self.validate_scope()
        self.options = options

    def __eq__(self, other: Any) -> bool:
        if type(self) != type(other):
            return False
        return bool(self.options == other.options)


_T = TypeVar("_T", bound=Optionable)


async def _construct_optionable(optionable: Type[_T]) -> _T:
    scoped_options = await Get(ScopedOptions, Scope(str(optionable.options_scope)))
    return optionable(scoped_options.options)
