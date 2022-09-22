# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import inspect
import re
from abc import ABCMeta
from itertools import chain
from typing import TYPE_CHECKING, Any, ClassVar, Iterable, TypeVar, cast

from pants import ox
from pants.engine.internals.selectors import AwaitableConstraints, Get
from pants.option.errors import OptionsError
from pants.option.option_types import collect_options_info
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.scope import Scope, ScopedOptions, ScopeInfo, normalize_scope
from pants.util.memo import memoized_classmethod

if TYPE_CHECKING:
    # Needed to avoid an import cycle.
    from pants.core.util_rules.environments import EnvironmentTarget
    from pants.engine.rules import Rule

_SubsystemT = TypeVar("_SubsystemT", bound="Subsystem")


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

    class EnvironmentAware(metaclass=ABCMeta):
        subsystem: Subsystem
        options: OptionValueContainer
        env_tgt: EnvironmentTarget

        def __getattribute__(self, __name: str) -> Any:
            from pants.core.util_rules.environments import get_option

            val = super().__getattribute__(__name)
            if __name == "options":
                return val

            try:
                if __name in self.options:
                    return get_option(__name, self)
            except AttributeError:
                pass

            return val

    @classmethod
    def rule(cls) -> Rule:
        """Returns a `TaskRule` that will construct the target Subsystem."""

        # Global-level imports are conditional, we need to re-import here for runtime use
        from pants.engine.rules import TaskRule

        partial_construct_subsystem: Any = functools.partial(_construct_subsytem, cls)

        # NB: We must populate several dunder methods on the partial function because partial
        # functions do not have these defined by default and the engine uses these values to
        # visualize functions in error messages and the rule graph.
        snake_scope = normalize_scope(cls.options_scope)
        name = f"construct_scope_{snake_scope}"
        partial_construct_subsystem.__name__ = name
        partial_construct_subsystem.__module__ = cls.__module__
        partial_construct_subsystem.__doc__ = cls.help

        # `inspect.getsourcelines` does not work under oxidation
        if not ox.is_oxidized:
            _, class_definition_lineno = inspect.getsourcelines(cls)
        else:
            class_definition_lineno = 0  # `inspect.getsourcelines` returns 0 when undefined.
        partial_construct_subsystem.__line_number__ = class_definition_lineno

        return TaskRule(
            output_type=cls,
            input_selectors=(),
            func=partial_construct_subsystem,
            input_gets=(
                AwaitableConstraints(
                    output_type=ScopedOptions, input_types=(Scope,), is_effect=False
                ),
            ),
            canonical_name=name,
        )

    @classmethod
    def rule_env_aware(cls) -> Rule:
        """Returns kwargs to construct a `TaskRule` that will construct the target Subsystem."""
        # Global-level imports are conditional, we need to re-import here for runtime use
        from pants.core.util_rules.environments import EnvironmentTarget
        from pants.engine.rules import TaskRule

        snake_scope = normalize_scope(cls.options_scope)
        name = f"construct_env_aware_scope_{snake_scope}"

        return TaskRule(
            output_type=cls.EnvironmentAware,
            input_selectors=(cls, EnvironmentTarget),
            func=_construct_env_aware,
            input_gets=(
                AwaitableConstraints(
                    output_type=ScopedOptions, input_types=(Scope,), is_effect=False
                ),
            ),
            canonical_name=name,
        )

    @memoized_classmethod
    def rules(cls: Any) -> Iterable[Rule]:
        from pants.core.util_rules.environments import add_option_fields_for
        from pants.engine.rules import Rule

        return [
            cls.rule(),
            cls.rule_env_aware(),
            *(cast(Rule, i) for i in add_option_fields_for(cls)),
        ]

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
    def register_options_on_scope(cls, options: Options):
        """Trigger registration of this Subsystem's options.

        Subclasses should not generally need to override this method.
        """
        register = options.registration_function_for_subsystem(cls)
        for options_info in chain(
            collect_options_info(cls), collect_options_info(cls.EnvironmentAware)
        ):
            register(*options_info.flag_names, **options_info.flag_options)

        # NB: If the class defined `register_options` we should call it
        if "register_options" in cls.__dict__:
            cls.register_options(register)  # type: ignore[attr-defined]

    def __init__(self, options: OptionValueContainer) -> None:
        self.validate_scope()
        self.options = options

    def __eq__(self, other: Any) -> bool:
        if type(self) != type(other):
            return False
        return bool(self.options == other.options)


async def _construct_subsytem(subsystem_typ: type[_SubsystemT]) -> _SubsystemT:
    scoped_options = await Get(ScopedOptions, Scope(str(subsystem_typ.options_scope)))
    return subsystem_typ(scoped_options.options)


async def _construct_env_aware(
    subsystem_instance: _SubsystemT,
    env_tgt: EnvironmentTarget,
) -> Subsystem.EnvironmentAware:
    t: Subsystem.EnvironmentAware = type(subsystem_instance).EnvironmentAware()
    # Runtime error which should alert subsystem authors and end users shouldn't see.
    # Inner type must explicitly declare a subclass, but mypy doesn't catch this.
    assert isinstance(t, Subsystem.EnvironmentAware)

    t.options = subsystem_instance.options
    t.subsystem = subsystem_instance
    t.env_tgt = env_tgt

    return t
