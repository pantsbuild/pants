# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import inspect
import re
from abc import ABCMeta
from typing import Any, ClassVar, TypeVar

from pants.base.deprecated import deprecated
from pants.engine.internals.selectors import AwaitableConstraints, Get
from pants.option.errors import OptionsError
from pants.option.option_types import collect_options_info
from pants.option.option_value_container import OptionValueContainer
from pants.option.scope import Scope, ScopedOptions, ScopeInfo, normalize_scope
from pants.util.docutil import doc_url


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
    @deprecated(
        removal_version="2.12.0.dev2",
        hint=(
            "Options are now registered by declaring class attributes using the types in "
            f"pants/option/option_types.py. See {doc_url('plugin-upgrade-guide')}"
        ),
    )
    def register_options(cls, register):
        """Register options for this Subsystem.

        Subclasses may override and call register(*args, **kwargs).
        """

    @classmethod
    def register_options_on_scope(cls, options):
        """Trigger registration of this Subsystem's options.

        Subclasses should not generally need to override this method.
        """
        register = options.registration_function_for_subsystem(cls)
        for options_info in collect_options_info(cls):
            register(*options_info.flag_names, **options_info.flag_options)

        # NB: If the class defined `register_options` we should call it
        if "register_options" in cls.__dict__:
            cls.register_options(register)

    def __init__(self, options: OptionValueContainer) -> None:
        self.validate_scope()
        self.options = options

    def __eq__(self, other: Any) -> bool:
        if type(self) != type(other):
            return False
        return bool(self.options == other.options)


_SubsystemT = TypeVar("_SubsystemT", bound=Subsystem)


async def _construct_subsytem(subsystem_typ: type[_SubsystemT]) -> _SubsystemT:
    scoped_options = await Get(ScopedOptions, Scope(str(subsystem_typ.options_scope)))
    return subsystem_typ(scoped_options.options)
