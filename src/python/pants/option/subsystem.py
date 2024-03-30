# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import functools
import inspect
import re
from abc import ABCMeta
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Iterable, Sequence, TypeVar, cast

from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.selectors import AwaitableConstraints, Get
from pants.engine.unions import UnionMembership, UnionRule, distinct_union_type_per_subclass
from pants.option.errors import OptionsError
from pants.option.option_types import OptionsInfo, collect_options_info
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.scope import Scope, ScopedOptions, ScopeInfo, normalize_scope
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap

if TYPE_CHECKING:
    # Needed to avoid an import cycle.
    from pants.core.util_rules.environments import EnvironmentTarget
    from pants.engine.rules import Rule

_SubsystemT = TypeVar("_SubsystemT", bound="Subsystem")


class _SubsystemMeta(ABCMeta):
    """Metaclass to link inner `EnvironmentAware` class with the enclosing subsystem."""

    def __init__(self, name, bases, namespace, **k):
        super().__init__(name, bases, namespace, **k)
        if (
            not (name == "Subsystem" and bases == ())
            and self.EnvironmentAware is not Subsystem.EnvironmentAware
        ):
            # Only `EnvironmentAware` subclasses should be linked to their enclosing scope
            if Subsystem.EnvironmentAware not in self.EnvironmentAware.__bases__:
                # Allow for `self.EnvironmentAware` to not need to explicitly derive from
                # `Subsystem.EnvironmentAware` (saving needless repetitive typing)
                self.EnvironmentAware = type(
                    "EnvironmentAware",
                    (
                        self.EnvironmentAware,
                        Subsystem.EnvironmentAware,
                        *self.EnvironmentAware.__bases__,
                    ),
                    {},
                )
            self.EnvironmentAware.subsystem = self


class Subsystem(metaclass=_SubsystemMeta):
    """A separable piece of functionality that may be reused across multiple tasks or other code.

    Subsystems encapsulate the configuration and initialization of things like JVMs,
    Python interpreters, SCMs and so on.

    Set the `help` class property with a description, which will be used in `./pants help`. For the
    best rendering, use soft wrapping (e.g. implicit string concatenation) within paragraphs, but
    hard wrapping (`\n`) to separate distinct paragraphs and/or lists.
    """

    options_scope: str
    help: ClassVar[str | Callable[[], str]]

    # Subclasses may override these to specify a deprecated former name for this Subsystem's scope.
    # Option values can be read from the deprecated scope, but a deprecation warning will be issued.
    # The deprecation warning becomes an error at the given Pants version (which must therefore be
    # a valid semver).
    deprecated_options_scope: str | None = None
    deprecated_options_scope_removal_version: str | None = None

    # // Note: must be aligned with the regex in src/rust/engine/options/src/id.rs.
    _scope_name_re = re.compile(r"^(?:[a-z0-9_])+(?:-(?:[a-z0-9_])+)*$")

    _rules: ClassVar[Sequence[Rule] | None] = None

    class EnvironmentAware(metaclass=ABCMeta):
        """A separate container for options that may be redefined by the runtime environment.

        To define environment-aware options, create an inner class in the `Subsystem` called
        `EnvironmentAware`. Option fields share their scope with their enclosing `Subsystem`,
        and the values of fields will default to the values set through Pants' configuration.

        To consume environment-aware options, inject the `EnvironmentAware` inner class into
        your rule.

        Optionally, it is possible to specify environment variables that are required when
        post-processing raw values provided by users (e.g. `<PATH>` special strings) by specifying
        `env_vars_used_by_options`, and consuming `_options_env` in your post-processing property.
        These environment variables will be requested at construction time.
        """

        subsystem: ClassVar[type[Subsystem]]
        env_vars_used_by_options: ClassVar[tuple[str, ...]] = ()

        options: OptionValueContainer
        env_tgt: EnvironmentTarget
        _options_env: EnvironmentVars = EnvironmentVars()

        def __getattribute__(self, __name: str) -> Any:
            from pants.core.util_rules.environments import resolve_environment_sensitive_option

            # Will raise an `AttributeError` if the attribute is not defined.
            # MyPy should stop that from ever happening.
            default = super().__getattribute__(__name)

            # Check to see whether there's a definition of this attribute at the class level.
            # If it returns `default` then the attribute on the instance is the same object
            # as defined at the class, or the attribute does not exist on the class,
            # and we don't really need to go any further.
            v = getattr(type(self), __name, default)
            if v is default:
                return default

            # Resolving an attribute on the class object will return the underlying descriptor.
            # If the descriptor is an `OptionsInfo`, we can resolve it against the environment
            # target.
            if isinstance(v, OptionsInfo):
                # If the value is not defined in the `EnvironmentTarget`, return the value
                # from the options system.
                override = resolve_environment_sensitive_option(v.flag_names[0], self)
                return override if override is not None else default

            # We should just return the default at this point.
            return default

        def _is_default(self, __name: str) -> bool:
            """Returns true if the value of the named option is unchanged from the default."""
            from pants.core.util_rules.environments import resolve_environment_sensitive_option

            v = getattr(type(self), __name)
            assert isinstance(v, OptionsInfo)

            return (
                # vars beginning with `_` are exposed as option names with the leading `_` stripped
                self.options.is_default(__name.lstrip("_"))
                and resolve_environment_sensitive_option(v.flag_names[0], self) is None
            )

    @classmethod
    def rules(cls: Any) -> Iterable[Rule]:
        # NB: This avoids using `memoized_classmethod` until its interaction with `mypy` can be improved.
        if cls._rules is None:
            from pants.core.util_rules.environments import add_option_fields_for
            from pants.engine.rules import Rule

            # nb. `rules` needs to be memoized so that repeated calls to add these rules
            # return exactly the same rule objects. As such, returning this generator
            # directly won't work, because the iterator needs to be replayable.
            def inner() -> Iterable[Rule]:
                yield cls._construct_subsystem_rule()
                if cls.EnvironmentAware is not Subsystem.EnvironmentAware:
                    yield cls._construct_env_aware_rule()
                    yield from (cast(Rule, i) for i in add_option_fields_for(cls.EnvironmentAware))

            cls._rules = tuple(inner())
        return cast("Sequence[Rule]", cls._rules)

    @distinct_union_type_per_subclass
    class PluginOption:
        pass

    @classmethod
    def register_plugin_options(cls, options_container: type) -> UnionRule:
        """Register additional options on the subsystem.

        In the `rules()` register.py entry-point, include `OtherSubsystem.register_plugin_options(<OptionsContainer>)`.
        `<OptionsContainer>` should be a type with option class attributes, similar to how they are
        defined for subsystems.

        This will register the option as a first-class citizen.
        Plugins can use this new option like any other.
        """
        return UnionRule(cls.PluginOption, options_container)

    @classmethod
    def _construct_subsystem_rule(cls) -> Rule:
        """Returns a `TaskRule` that will construct the target Subsystem."""

        # Global-level imports are conditional, we need to re-import here for runtime use
        from pants.engine.rules import TaskRule

        partial_construct_subsystem: Any = functools.partial(_construct_subsystem, cls)

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

        return TaskRule(
            output_type=cls,
            parameters=FrozenDict(),
            awaitables=(
                AwaitableConstraints(
                    rule_id=None,
                    output_type=ScopedOptions,
                    explicit_args_arity=0,
                    input_types=(Scope,),
                    is_effect=False,
                ),
            ),
            masked_types=(),
            func=partial_construct_subsystem,
            canonical_name=name,
        )

    @classmethod
    def _construct_env_aware_rule(cls) -> Rule:
        """Returns a `TaskRule` that will construct the target Subsystem.EnvironmentAware."""
        # Global-level imports are conditional, we need to re-import here for runtime use
        from pants.core.util_rules.environments import EnvironmentTarget
        from pants.engine.rules import TaskRule

        snake_scope = normalize_scope(cls.options_scope)
        name = f"construct_env_aware_scope_{snake_scope}"

        # placate the rule graph visualizer.
        @functools.wraps(_construct_env_aware)
        async def inner(*a, **k):
            return await _construct_env_aware(*a, **k)

        inner.__line_number__ = 0  # type: ignore[attr-defined]

        return TaskRule(
            output_type=cls.EnvironmentAware,
            parameters=FrozenDict({"subsystem_instance": cls, "env_tgt": EnvironmentTarget}),
            awaitables=(
                AwaitableConstraints(
                    rule_id=None,
                    output_type=EnvironmentVars,
                    explicit_args_arity=0,
                    input_types=(EnvironmentVarsRequest,),
                    is_effect=False,
                ),
            ),
            masked_types=(),
            func=inner,
            canonical_name=name,
        )

    @classmethod
    def is_valid_scope_name(cls, s: str) -> bool:
        return s == "" or (cls._scope_name_re.match(s) is not None and s != "pants")

    @classmethod
    def validate_scope(cls) -> None:
        options_scope = getattr(cls, "options_scope", None)
        if options_scope is None:
            raise OptionsError(f"{cls.__name__} must set options_scope.")
        if not cls.is_valid_scope_name(options_scope):
            raise OptionsError(
                softwrap(
                    """
                    Options scope "{options_scope}" is not valid.

                    Replace in code with a new scope name consisting of only lower-case letters,
                    digits, underscores, and non-consecutive dashes.
                    """
                )
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
    def register_options_on_scope(cls, options: Options, union_membership: UnionMembership):
        """Trigger registration of this Subsystem's options.

        Subclasses should not generally need to override this method.
        """
        register = options.registration_function_for_subsystem(cls)
        plugin_option_containers = union_membership.get(cls.PluginOption)
        for options_info in collect_options_info(cls):
            register(*options_info.flag_names, **options_info.flag_options)
        for options_info in collect_options_info(cls.EnvironmentAware):
            register(*options_info.flag_names, environment_aware=True, **options_info.flag_options)
        for options_info in (
            option
            for container in plugin_option_containers
            for option in collect_options_info(container)
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


async def _construct_subsystem(subsystem_typ: type[_SubsystemT]) -> _SubsystemT:
    scoped_options = await Get(ScopedOptions, Scope(str(subsystem_typ.options_scope)))
    return subsystem_typ(scoped_options.options)


async def _construct_env_aware(
    subsystem_instance: _SubsystemT,
    env_tgt: EnvironmentTarget,
) -> Subsystem.EnvironmentAware:
    t: Subsystem.EnvironmentAware = type(subsystem_instance).EnvironmentAware()
    # `_SubSystemMeta` metaclass should ensure that `EnvironmentAware` actually subclasses
    # `EnvironmentAware`, but if an implementer does something egregious, it's best we
    # catch it.
    assert isinstance(t, Subsystem.EnvironmentAware)

    t.options = subsystem_instance.options
    t.env_tgt = env_tgt

    if t.env_vars_used_by_options:
        t._options_env = await Get(
            EnvironmentVars, EnvironmentVarsRequest(t.env_vars_used_by_options)
        )

    return t
