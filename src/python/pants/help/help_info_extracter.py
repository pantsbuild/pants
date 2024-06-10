# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import ast
import dataclasses
import difflib
import inspect
import itertools
import json
from collections import defaultdict, namedtuple
from dataclasses import dataclass
from enum import Enum
from functools import reduce
from itertools import chain
from pathlib import Path
from typing import (
    Any,
    Callable,
    DefaultDict,
    Iterator,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
    get_type_hints,
)

import pkg_resources

import pants.backend
from pants.base import deprecated
from pants.build_graph.build_configuration import BuildConfiguration
from pants.core.util_rules.environments import option_field_name_for
from pants.engine.goal import GoalSubsystem
from pants.engine.internals.parser import BuildFileSymbolInfo, BuildFileSymbolsInfo, Registrar
from pants.engine.rules import Rule, TaskRule
from pants.engine.target import Field, RegisteredTargetTypes, StringField, Target, TargetGenerator
from pants.engine.unions import UnionMembership, UnionRule, is_union
from pants.option.option_util import is_dict_option, is_list_option
from pants.option.options import Options
from pants.option.parser import OptionValueHistory, Parser
from pants.option.scope import ScopeInfo
from pants.util.frozendict import LazyFrozenDict
from pants.util.strutil import first_paragraph, strval

T = TypeVar("T")


class HelpJSONEncoder(json.JSONEncoder):
    """Class for JSON-encoding help data (including option values).

    Note that JSON-encoded data is not intended to be decoded back. It exists purely for terminal
    and browser help display.
    """

    def default(self, o):
        if callable(o):
            return o.__name__
        if isinstance(o, type):
            return type.__name__
        if isinstance(o, Enum):
            return o.value
        return super().default(o)


def to_help_str(val) -> str:
    if isinstance(val, (list, dict)):
        return json.dumps(val, sort_keys=True, indent=2, cls=HelpJSONEncoder)
    if isinstance(val, Enum):
        return str(val.value)
    else:
        return str(val)


@dataclass(frozen=True)
class OptionHelpInfo:
    """A container for help information for a single option.

    display_args: Arg strings suitable for display in help text, including value examples
                  (e.g., [-f, --[no]-foo-bar, --baz=<metavar>].)
    comma_separated_display_args: Display args as a comma-delimited string, used in
                                  reference documentation.
    scoped_cmd_line_args: The explicitly scoped raw flag names allowed anywhere on the cmd line,
                          (e.g., [--scope-baz, --no-scope-baz, --scope-qux])
    unscoped_cmd_line_args: The unscoped raw flag names allowed on the cmd line in this option's
                            scope context (e.g., [--baz, --no-baz, --qux])
    env_var: The environment variable that set's the option.
    config_key: The config key for this option (in the section named for its scope).
    target_field_name: The name for the field that overrides this option in `local_environment`,
                       `remote_environment`, or `docker_environment`, if the option is environment-
                       aware, else `None`.
    typ: The type of the option.
    default: The value of this option if no flags are specified (derived from config and env vars).
    help: The help message registered for this option.
    deprecated_message: If deprecated: A message explaining that this option is deprecated at
                        removal_version.
    removal_version: If deprecated: The version at which this option is to be removed.
    removal_hint: If deprecated: The removal hint message registered for this option.
    choices: If this option has a constrained set of choices, a tuple of the stringified choices.
    fromfile: Supports reading the option value from a file when using `@filepath`.
    """

    display_args: tuple[str, ...]
    comma_separated_display_args: str
    scoped_cmd_line_args: tuple[str, ...]
    unscoped_cmd_line_args: tuple[str, ...]
    env_var: str
    config_key: str
    target_field_name: str | None
    typ: type
    default: Any
    help: str
    deprecation_active: bool
    deprecated_message: str | None
    removal_version: str | None
    removal_hint: str | None
    choices: tuple[str, ...] | None
    comma_separated_choices: str | None
    value_history: OptionValueHistory | None
    fromfile: bool


@dataclass(frozen=True)
class OptionScopeHelpInfo:
    """A container for help information for a scope of options.

    scope: The scope of the described options.
    provider: Which backend or plugin registered this scope.
    deprecated_scope: A deprecated scope name for this scope. A scope that has a deprecated scope
      will be represented by two objects - one of which will have scope==deprecated_scope.
    basic|advanced|deprecated: A list of OptionHelpInfo for the options in that group.
    """

    scope: str
    description: str
    provider: str
    is_goal: bool  # True iff the scope belongs to a GoalSubsystem.
    deprecated_scope: Optional[str]
    basic: tuple[OptionHelpInfo, ...]
    advanced: tuple[OptionHelpInfo, ...]
    deprecated: tuple[OptionHelpInfo, ...]

    def is_deprecated_scope(self):
        """Returns True iff this scope is deprecated.

        We may choose not to show deprecated scopes when enumerating scopes, but still want to show
        help for individual deprecated scopes when explicitly requested.
        """
        return self.scope == self.deprecated_scope

    def collect_unscoped_flags(self) -> list[str]:
        flags: list[str] = []
        for options in (self.basic, self.advanced, self.deprecated):
            for ohi in options:
                flags.extend(ohi.unscoped_cmd_line_args)
        return flags

    def collect_scoped_flags(self) -> list[str]:
        flags: list[str] = []
        for options in (self.basic, self.advanced, self.deprecated):
            for ohi in options:
                flags.extend(ohi.scoped_cmd_line_args)
        return flags


@dataclass(frozen=True)
class GoalHelpInfo:
    """A container for help information for a goal."""

    name: str
    description: str
    provider: str
    is_implemented: bool  # True iff all unions required by the goal are implemented.
    consumed_scopes: tuple[str, ...]  # The scopes of subsystems consumed by this goal.


def pretty_print_type_hint(hint: Any) -> str:
    if getattr(hint, "__origin__", None) == Union:
        union_members = hint.__args__
        hint_str = " | ".join(pretty_print_type_hint(member) for member in union_members)
    # NB: Checking for GenericMeta is only for Python 3.6 because some `typing` classes like
    # `typing.Iterable` have its type, whereas Python 3.7+ removes it. Remove this check
    # once we drop support for Python 3.6.
    elif isinstance(hint, type) and not str(type(hint)) == "<class 'typing.GenericMeta'>":
        hint_str = hint.__name__
    else:
        hint_str = str(hint)
    return hint_str.replace("typing.", "").replace("NoneType", "None")


@dataclass(frozen=True)
class TargetFieldHelpInfo:
    """A container for help information for a field in a target type."""

    alias: str
    provider: str
    description: str
    type_hint: str
    required: bool
    default: str | None

    @classmethod
    def create(cls, field: type[Field], *, provider: str) -> TargetFieldHelpInfo:
        raw_value_type = get_type_hints(field.compute_value)["raw_value"]
        type_hint = pretty_print_type_hint(raw_value_type)

        # Check if the field only allows for certain choices.
        if issubclass(field, StringField) and field.valid_choices is not None:
            valid_choices = sorted(
                field.valid_choices
                if isinstance(field.valid_choices, tuple)
                else (choice.value for choice in field.valid_choices)
            )
            type_hint = " | ".join([*(repr(c) for c in valid_choices), "None"])

        if field.required:
            # We hackily remove `None` as a valid option for the field when it's required. This
            # greatly simplifies Field definitions because it means that they don't need to
            # override the type hints for `PrimitiveField.compute_value()` and
            # `AsyncField.sanitize_raw_value()` to indicate that `None` is an invalid type.
            type_hint = type_hint.replace(" | None", "")

        return cls(
            alias=field.alias,
            provider=provider,
            description=strval(field.help),
            type_hint=type_hint,
            required=field.required,
            default=(
                repr(field.default) if (not field.required and field.default is not None) else None
            ),
        )


@dataclass(frozen=True)
class TargetTypeHelpInfo:
    """A container for help information for a target type."""

    alias: str
    provider: str
    summary: str
    description: str
    fields: tuple[TargetFieldHelpInfo, ...]

    @classmethod
    def create(
        cls,
        target_type: type[Target],
        *,
        provider: str,
        union_membership: UnionMembership,
        get_field_type_provider: Callable[[type[Field]], str] | None,
    ) -> TargetTypeHelpInfo:
        fields = list(target_type.class_field_types(union_membership=union_membership))
        if issubclass(target_type, TargetGenerator):
            # NB: Even though the moved_fields will never be present on a constructed
            # TargetGenerator, they are legal arguments... and that is what most help consumers
            # are interested in.
            fields.extend(target_type.moved_fields)
        helpstr = strval(target_type.help)
        return cls(
            alias=target_type.alias,
            provider=provider,
            summary=first_paragraph(helpstr),
            description=helpstr,
            fields=tuple(
                TargetFieldHelpInfo.create(
                    field,
                    provider=""
                    if get_field_type_provider is None
                    else get_field_type_provider(field),
                )
                for field in fields
                if not field.alias.startswith("_") and field.removal_version is None
            ),
        )


def maybe_cleandoc(doc: str | None) -> str | None:
    return doc and inspect.cleandoc(doc)


@dataclass(frozen=True)
class RuleInfo:
    """A container for help information for a rule.

    The `description` is the `desc` provided to the `@rule` decorator, and `documentation` is the
    rule's doc string.
    """

    name: str
    description: str | None
    documentation: str | None
    provider: str
    output_type: str
    input_types: tuple[str, ...]
    awaitables: tuple[str, ...]

    @classmethod
    def create(cls, rule: TaskRule, provider: str) -> RuleInfo:
        return cls(
            name=rule.canonical_name,
            description=rule.desc,
            documentation=maybe_cleandoc(rule.func.__doc__),
            provider=provider,
            input_types=tuple(typ.__name__ for typ in rule.parameters.values()),
            awaitables=tuple(str(constraints) for constraints in rule.awaitables),
            output_type=rule.output_type.__name__,
        )


@dataclass(frozen=True)
class PluginAPITypeInfo:
    """A container for help information for a plugin API type.

    Plugin API types are used as input parameters and output results for rules.
    """

    name: str
    module: str
    documentation: str | None
    provider: tuple[str, ...]
    is_union: bool
    union_type: str | None
    union_members: tuple[str, ...]
    dependencies: tuple[str, ...]
    dependents: tuple[str, ...]
    returned_by_rules: tuple[str, ...]
    consumed_by_rules: tuple[str, ...]
    used_in_rules: tuple[str, ...]

    @property
    def fully_qualified_name(self) -> str:
        return f"{self.module}.{self.name}"

    @staticmethod
    def fully_qualified_name_from_type(t: type):
        return f"{t.__module__}.{t.__qualname__}"

    @classmethod
    def create(
        cls, api_type: type, rules: Sequence[Rule | UnionRule], **kwargs
    ) -> PluginAPITypeInfo:
        union_type: str | None = None
        for rule in filter(cls._member_type_for(api_type), rules):
            # All filtered rules out of `_member_type_for` will be `UnionRule`s.
            union_type = cast(UnionRule, rule).union_base.__name__
            break

        task_rules = [rule for rule in rules if isinstance(rule, TaskRule)]

        return cls(
            name=api_type.__qualname__,
            module=api_type.__module__,
            documentation=maybe_cleandoc(api_type.__doc__),
            is_union=is_union(api_type),
            union_type=union_type,
            consumed_by_rules=cls._all_rules(cls._rule_consumes(api_type), task_rules),
            returned_by_rules=cls._all_rules(cls._rule_returns(api_type), task_rules),
            used_in_rules=cls._all_rules(cls._rule_uses(api_type), task_rules),
            **kwargs,
        )

    @staticmethod
    def _all_rules(
        satisfies: Callable[[TaskRule], bool], rules: Sequence[TaskRule]
    ) -> tuple[str, ...]:
        return tuple(sorted(rule.canonical_name for rule in filter(satisfies, rules)))

    @staticmethod
    def _rule_consumes(api_type: type) -> Callable[[TaskRule], bool]:
        def satisfies(rule: TaskRule) -> bool:
            return api_type in rule.parameters.values()

        return satisfies

    @staticmethod
    def _rule_returns(api_type: type) -> Callable[[TaskRule], bool]:
        def satisfies(rule: TaskRule) -> bool:
            return rule.output_type is api_type

        return satisfies

    @staticmethod
    def _rule_uses(api_type: type) -> Callable[[TaskRule], bool]:
        def satisfies(rule: TaskRule) -> bool:
            return any(
                api_type in (*constraint.input_types, constraint.output_type)
                for constraint in rule.awaitables
            )

        return satisfies

    @staticmethod
    def _member_type_for(api_type: type) -> Callable[[Rule | UnionRule], bool]:
        def satisfies(rule: Rule | UnionRule) -> bool:
            return isinstance(rule, UnionRule) and rule.union_member is api_type

        return satisfies

    def merged_with(self, that: PluginAPITypeInfo) -> PluginAPITypeInfo:
        def merge_tuples(l, r):
            return tuple(sorted({*l, *r}))

        return PluginAPITypeInfo(
            self.name,
            self.module,
            self.documentation,
            merge_tuples(self.provider, that.provider),
            self.is_union,
            self.union_type,
            merge_tuples(self.union_members, that.union_members),
            merge_tuples(self.dependencies, that.dependencies),
            merge_tuples(self.dependents, that.dependents),
            merge_tuples(self.returned_by_rules, that.returned_by_rules),
            merge_tuples(self.consumed_by_rules, that.consumed_by_rules),
            merge_tuples(self.used_in_rules, that.used_in_rules),
        )


@dataclass(frozen=True)
class BackendHelpInfo:
    name: str
    description: str
    enabled: bool
    provider: str


@dataclass(frozen=True)
class BuildFileSymbolHelpInfo:
    name: str
    is_target: bool
    signature: str | None
    documentation: str | None


@dataclass(frozen=True)
class AllHelpInfo:
    """All available help info."""

    scope_to_help_info: LazyFrozenDict[str, OptionScopeHelpInfo]
    name_to_goal_info: LazyFrozenDict[str, GoalHelpInfo]
    name_to_target_type_info: LazyFrozenDict[str, TargetTypeHelpInfo]
    name_to_rule_info: LazyFrozenDict[str, RuleInfo]
    name_to_api_type_info: LazyFrozenDict[str, PluginAPITypeInfo]
    name_to_backend_help_info: LazyFrozenDict[str, BackendHelpInfo]
    name_to_build_file_info: LazyFrozenDict[str, BuildFileSymbolHelpInfo]
    env_var_to_help_info: LazyFrozenDict[str, OptionHelpInfo]

    def non_deprecated_option_scope_help_infos(self):
        for oshi in self.scope_to_help_info.values():
            if not oshi.is_deprecated_scope():
                yield oshi

    def asdict(self) -> dict[str, Any]:
        return {
            field: {thing: dataclasses.asdict(info) for thing, info in value.items()}
            for field, value in dataclasses.asdict(self).items()
        }


ConsumedScopesMapper = Callable[[str], Tuple[str, ...]]


class HelpInfoExtracter:
    """Extracts information useful for displaying help from option registration args."""

    @classmethod
    def get_all_help_info(
        cls,
        options: Options,
        union_membership: UnionMembership,
        consumed_scopes_mapper: ConsumedScopesMapper,
        registered_target_types: RegisteredTargetTypes,
        build_symbols: BuildFileSymbolsInfo,
        build_configuration: BuildConfiguration | None = None,
    ) -> AllHelpInfo:
        def option_scope_help_info_loader_for(
            scope_info: ScopeInfo,
        ) -> Callable[[], OptionScopeHelpInfo]:
            def load() -> OptionScopeHelpInfo:
                options.for_scope(scope_info.scope)  # Force parsing.
                subsystem_cls = scope_info.subsystem_cls
                if not scope_info.description:
                    cls_name = (
                        f"{subsystem_cls.__module__}.{subsystem_cls.__qualname__}"
                        if subsystem_cls
                        else ""
                    )
                    raise ValueError(
                        f"Subsystem {cls_name} with scope `{scope_info.scope}` has no description. "
                        f"Add a class property `help`."
                    )
                provider = ""
                if subsystem_cls is not None and build_configuration is not None:
                    provider = cls.get_provider(
                        build_configuration.subsystem_to_providers.get(subsystem_cls),
                        subsystem_cls.__module__,
                    )
                return HelpInfoExtracter(scope_info.scope).get_option_scope_help_info(
                    scope_info.description,
                    options.get_parser(scope_info.scope),
                    # `filter` should be treated as a subsystem for `help`, even though it still
                    # works as a goal for backwards compatibility.
                    scope_info.is_goal if scope_info.scope != "filter" else False,
                    provider,
                    scope_info.deprecated_scope,
                )

            return load

        def goal_help_info_loader_for(scope_info: ScopeInfo) -> Callable[[], GoalHelpInfo]:
            def load() -> GoalHelpInfo:
                subsystem_cls = scope_info.subsystem_cls
                assert subsystem_cls is not None
                if build_configuration is not None:
                    provider = cls.get_provider(
                        build_configuration.subsystem_to_providers.get(subsystem_cls),
                        subsystem_cls.__module__,
                    )
                goal_subsystem_cls = cast(Type[GoalSubsystem], subsystem_cls)
                return GoalHelpInfo(
                    goal_subsystem_cls.name,
                    scope_info.description,
                    provider,
                    goal_subsystem_cls.activated(union_membership),
                    consumed_scopes_mapper(scope_info.scope),
                )

            return load

        def target_type_info_for(target_type: type[Target]) -> Callable[[], TargetTypeHelpInfo]:
            def load() -> TargetTypeHelpInfo:
                return TargetTypeHelpInfo.create(
                    target_type,
                    union_membership=union_membership,
                    provider=cls.get_provider(
                        build_configuration
                        and build_configuration.target_type_to_providers.get(target_type)
                        or None,
                        target_type.__module__,
                    ),
                    get_field_type_provider=lambda field_type: cls.get_provider(
                        (
                            build_configuration.union_rule_to_providers.get(
                                UnionRule(target_type.PluginField, field_type)
                            )
                            if build_configuration is not None
                            else None
                        ),
                        field_type.__module__,
                    ),
                )

            return load

        def lazily(value: T) -> Callable[[], T]:
            return lambda: value

        known_scope_infos = sorted(options.known_scope_to_info.values(), key=lambda x: x.scope)
        scope_to_help_info = LazyFrozenDict(
            {
                scope_info.scope: option_scope_help_info_loader_for(scope_info)
                for scope_info in known_scope_infos
                if not scope_info.scope.startswith("_")
            }
        )

        env_var_to_help_info = LazyFrozenDict(
            {
                ohi.env_var: lazily(ohi)
                for oshi in scope_to_help_info.values()
                for ohi in chain(oshi.basic, oshi.advanced, oshi.deprecated)
            }
        )

        name_to_goal_info = LazyFrozenDict(
            {
                scope_info.scope: goal_help_info_loader_for(scope_info)
                for scope_info in known_scope_infos
                if (
                    scope_info.is_goal
                    and not scope_info.scope.startswith("_")
                    # `filter` should be treated as a subsystem for `help`, even though it still
                    # works as a goal for backwards compatibility.
                    and scope_info.scope != "filter"
                )
            }
        )

        name_to_target_type_info = LazyFrozenDict(
            {
                alias: target_type_info_for(target_type)
                for alias, target_type in registered_target_types.aliases_to_types.items()
                if (target_type.removal_version is None and alias != target_type.deprecated_alias)
            }
        )

        return AllHelpInfo(
            scope_to_help_info=scope_to_help_info,
            name_to_goal_info=name_to_goal_info,
            name_to_target_type_info=name_to_target_type_info,
            name_to_rule_info=cls.get_rule_infos(build_configuration),
            name_to_api_type_info=cls.get_api_type_infos(build_configuration, union_membership),
            name_to_backend_help_info=cls.get_backend_help_info(options),
            name_to_build_file_info=cls.get_build_file_info(build_symbols),
            env_var_to_help_info=env_var_to_help_info,
        )

    @staticmethod
    def compute_default(**kwargs) -> Any:
        """Compute the default val for help display for an option registered with these kwargs."""
        # If the kwargs already determine a string representation of the default for use in help
        # messages, use that.
        default_help_repr = kwargs.get("default_help_repr")
        if default_help_repr is not None:
            return str(default_help_repr)  # Should already be a string, but might as well be safe.

        ranked_default = kwargs.get("default")
        fallback: Any = None
        if is_list_option(kwargs):
            fallback = []
        elif is_dict_option(kwargs):
            fallback = {}
        default = (
            ranked_default.value
            if ranked_default and ranked_default.value is not None
            else fallback
        )
        return default

    @staticmethod
    def stringify_type(t: type) -> str:
        if t == dict:
            return "{'key1': val1, 'key2': val2, ...}"
        return f"<{t.__name__}>"

    @staticmethod
    def compute_metavar(kwargs):
        """Compute the metavar to display in help for an option registered with these kwargs."""

        stringify = HelpInfoExtracter.stringify_type

        metavar = kwargs.get("metavar")
        if not metavar:
            if is_list_option(kwargs):
                member_typ = kwargs.get("member_type", str)
                metavar = stringify(member_typ)
                # In a cmd-line list literal, string members must be quoted.
                if member_typ == str:
                    metavar = f"'{metavar}'"
            elif is_dict_option(kwargs):
                metavar = f'"{stringify(dict)}"'
            else:
                metavar = stringify(kwargs.get("type", str))
        if is_list_option(kwargs):
            # For lists, the metavar (either explicit or deduced) is the representation
            # of a single list member, so we turn the help string into a list of those here.
            return f'"[{metavar}, {metavar}, ...]"'
        return metavar

    @staticmethod
    def compute_choices(kwargs) -> tuple[str, ...] | None:
        """Compute the option choices to display."""
        typ = kwargs.get("type", [])
        member_type = kwargs.get("member_type", str)
        if typ == list and inspect.isclass(member_type) and issubclass(member_type, Enum):
            return tuple(choice.value for choice in member_type)
        elif inspect.isclass(typ) and issubclass(typ, Enum):
            return tuple(choice.value for choice in typ)
        elif "choices" in kwargs:
            return tuple(str(choice) for choice in kwargs["choices"])
        else:
            return None

    @staticmethod
    def get_provider(providers: tuple[str, ...] | None, hint: str | None = None) -> str:
        """Get the best match for the provider.

        To take advantage of provider names being modules, `hint` should be something like the a
        subsystem's `__module__` or a rule's `canonical_name`.
        """
        if not providers:
            return ""
        if not hint:
            # Pick the shortest backend name.
            return sorted(providers, key=len)[0]

        # Pick the one closest to `hint`.
        # No cutoff and max 1 result guarantees a result with a single element.
        [provider] = difflib.get_close_matches(hint, providers, n=1, cutoff=0.0)
        return provider

    @staticmethod
    def maybe_cleandoc(doc: str | None) -> str | None:
        return doc and inspect.cleandoc(doc)

    @staticmethod
    def get_module_docstring(filename: str) -> str:
        with open(filename) as fd:
            return ast.get_docstring(ast.parse(fd.read(), filename)) or ""

    @classmethod
    def get_rule_infos(
        cls, build_configuration: BuildConfiguration | None
    ) -> LazyFrozenDict[str, RuleInfo]:
        if build_configuration is None:
            return LazyFrozenDict({})

        def rule_info_loader(rule: TaskRule, provider: str) -> Callable[[], RuleInfo]:
            def load() -> RuleInfo:
                return RuleInfo.create(rule, provider)

            return load

        return LazyFrozenDict(
            {
                rule.canonical_name: rule_info_loader(
                    rule, cls.get_provider(providers, rule.canonical_name)
                )
                for rule, providers in build_configuration.rule_to_providers.items()
                if isinstance(rule, TaskRule)
            }
        )

    @classmethod
    def get_api_type_infos(
        cls, build_configuration: BuildConfiguration | None, union_membership: UnionMembership
    ) -> LazyFrozenDict[str, PluginAPITypeInfo]:
        if build_configuration is None:
            return LazyFrozenDict({})

        # The type narrowing achieved with the above `if` does not extend to the created closures of
        # the nested functions in this body, so instead we capture it in a new variable.
        bc = build_configuration

        known_providers = cast(
            "set[str]",
            set(
                chain.from_iterable(
                    chain.from_iterable(cast(dict, providers).values())
                    for providers in (
                        bc.subsystem_to_providers,
                        bc.target_type_to_providers,
                        bc.rule_to_providers,
                        bc.union_rule_to_providers,
                    )
                )
            ),
        )

        def _find_provider(api_type: type) -> str:
            provider = api_type.__module__
            while provider:
                if provider in known_providers:
                    return provider
                if "." not in provider:
                    break
                provider = provider.rsplit(".", 1)[0]
            # Unknown provider, depend directly on the type's module.
            return api_type.__module__

        def _rule_dependencies(rule: TaskRule) -> Iterator[type]:
            yield from rule.parameters.values()
            for constraint in rule.awaitables:
                yield constraint.output_type

        def _extract_api_types() -> Iterator[tuple[type, str, tuple[type, ...]]]:
            """Return all possible types we encounter in all known rules with provider and
            dependencies."""
            for rule, providers in bc.rule_to_providers.items():
                if not isinstance(rule, TaskRule):
                    continue
                provider = cls.get_provider(providers, rule.canonical_name)
                yield rule.output_type, provider, tuple(_rule_dependencies(rule))

                for constraint in rule.awaitables:
                    for input_type in constraint.input_types:
                        yield input_type, _find_provider(input_type), ()

            union_bases: set[type] = set()
            for union_rule, providers in bc.union_rule_to_providers.items():
                provider = cls.get_provider(providers, union_rule.union_member.__module__)
                union_bases.add(union_rule.union_base)
                yield union_rule.union_member, provider, (union_rule.union_base,)

            for union_base in union_bases:
                yield union_base, _find_provider(union_base), ()

        all_types_with_dependencies = list(_extract_api_types())
        all_types = {api_type for api_type, _, _ in all_types_with_dependencies}
        type_graph: DefaultDict[type, dict[str, tuple[str, ...]]] = defaultdict(dict)

        # Calculate type graph.
        for api_type in all_types:
            # Collect all providers first, as we need them up-front for the dependencies/dependents.
            type_graph[api_type]["providers"] = tuple(
                sorted(
                    {
                        provider
                        for a_type, provider, _ in all_types_with_dependencies
                        if provider and a_type is api_type
                    }
                )
            )

        for api_type in all_types:
            # Resolve type dependencies to providers.
            type_graph[api_type]["dependencies"] = tuple(
                sorted(
                    set(
                        chain.from_iterable(
                            type_graph[dependency].setdefault(
                                "providers", (_find_provider(dependency),)
                            )
                            for a_type, _, dependencies in all_types_with_dependencies
                            if a_type is api_type
                            for dependency in dependencies
                        )
                    )
                    - set(
                        # Exclude providers from list of dependencies.
                        type_graph[api_type]["providers"]
                    )
                )
            )

        # Add a dependent on the target type for each dependency.
        type_dependents: DefaultDict[type, set[str]] = defaultdict(set)
        for _, provider, dependencies in all_types_with_dependencies:
            if not provider:
                continue
            for target_type in dependencies:
                type_dependents[target_type].add(provider)
        for api_type, dependents in type_dependents.items():
            type_graph[api_type]["dependents"] = tuple(
                sorted(
                    dependents
                    - set(
                        # Exclude providers from list of dependents.
                        type_graph[api_type]["providers"][0]
                    )
                )
            )

        rules = cast(
            "tuple[Rule | UnionRule]",
            tuple(
                chain(
                    bc.rule_to_providers.keys(),
                    bc.union_rule_to_providers.keys(),
                )
            ),
        )

        def get_api_type_info(api_types: tuple[type, ...]):
            """Gather the info from each of the types and aggregate it.

            The gathering is the expensive operation, and we can only aggregate once we've gathered.
            """

            def load() -> PluginAPITypeInfo:
                gatherered_infos = [
                    PluginAPITypeInfo.create(
                        api_type,
                        rules,
                        provider=type_graph[api_type]["providers"],
                        dependencies=type_graph[api_type]["dependencies"],
                        dependents=type_graph[api_type].get("dependents", ()),
                        union_members=tuple(
                            sorted(member.__qualname__ for member in union_membership.get(api_type))
                        ),
                    )
                    for api_type in api_types
                ]
                return reduce(lambda x, y: x.merged_with(y), gatherered_infos)

            return load

        # We want to provide a lazy dict so we don't spend so long doing the info gathering.
        # We provide a list of the types here, and the lookup function performs the gather and the aggregation
        api_type_name = PluginAPITypeInfo.fully_qualified_name_from_type
        all_types_sorted = sorted(all_types, key=api_type_name)
        infos: dict[str, Callable[[], PluginAPITypeInfo]] = {
            k: get_api_type_info(tuple(v))
            for k, v in itertools.groupby(all_types_sorted, key=api_type_name)
        }

        return LazyFrozenDict(infos)

    @classmethod
    def get_backend_help_info(cls, options: Options) -> LazyFrozenDict[str, BackendHelpInfo]:
        DiscoveredBackend = namedtuple(
            "DiscoveredBackend", "provider, name, register_py, enabled", defaults=(False,)
        )

        def discover_source_backends(root: Path, is_source_root: bool) -> set[DiscoveredBackend]:
            provider = root.name
            source_root = f"{root}/" if is_source_root else f"{root.parent}/"
            register_pys = root.glob("**/register.py")
            backends = {
                DiscoveredBackend(
                    provider,
                    str(register_py.parent).replace(source_root, "").replace("/", "."),
                    str(register_py),
                )
                for register_py in register_pys
            }
            return backends

        def discover_plugin_backends(entry_point_name: str) -> set[DiscoveredBackend]:
            backends = {
                DiscoveredBackend(
                    entry_point.dist.project_name,
                    entry_point.module_name,
                    str(
                        Path(entry_point.dist.location)
                        / (entry_point.module_name.replace(".", "/") + ".py")
                    ),
                    True,
                )
                for entry_point in pkg_resources.iter_entry_points(entry_point_name)
                if entry_point.dist is not None
            }
            return backends

        global_options = options.for_global_scope()
        builtin_backends = discover_source_backends(
            Path(pants.backend.__file__).parent.parent, is_source_root=False
        )
        inrepo_backends = chain.from_iterable(
            discover_source_backends(Path(path_entry), is_source_root=True)
            for path_entry in global_options.pythonpath
        )
        plugin_backends = discover_plugin_backends("pantsbuild.plugin")
        enabled_backends = {
            "pants.core",
            "pants.backend.project_info",
            *global_options.backend_packages,
        }

        def get_backend_help_info_loader(
            discovered_backend: DiscoveredBackend,
        ) -> Callable[[], BackendHelpInfo]:
            def load() -> BackendHelpInfo:
                return BackendHelpInfo(
                    name=discovered_backend.name,
                    description=cls.get_module_docstring(discovered_backend.register_py),
                    enabled=(
                        discovered_backend.enabled or discovered_backend.name in enabled_backends
                    ),
                    provider=discovered_backend.provider,
                )

            return load

        return LazyFrozenDict(
            {
                discovered_backend.name: get_backend_help_info_loader(discovered_backend)
                for discovered_backend in sorted(
                    chain(builtin_backends, inrepo_backends, plugin_backends)
                )
            }
        )

    @staticmethod
    def get_build_file_info(
        build_symbols: BuildFileSymbolsInfo,
    ) -> LazyFrozenDict[str, BuildFileSymbolHelpInfo]:
        def get_build_file_symbol_help_info_loader(
            symbol: BuildFileSymbolInfo,
        ) -> Callable[[], BuildFileSymbolHelpInfo]:
            def load() -> BuildFileSymbolHelpInfo:
                return BuildFileSymbolHelpInfo(
                    name=symbol.name,
                    is_target=isinstance(symbol.value, Registrar),
                    signature=symbol.signature,
                    documentation=symbol.help,
                )

            return load

        return LazyFrozenDict(
            {
                symbol.name: get_build_file_symbol_help_info_loader(symbol)
                for symbol in build_symbols.info.values()
            }
        )

    def __init__(self, scope: str):
        self._scope = scope
        self._scope_prefix = scope.replace(".", "-")

    def get_option_scope_help_info(
        self,
        description: str,
        parser: Parser,
        is_goal: bool,
        provider: str = "",
        deprecated_scope: Optional[str] = None,
    ) -> OptionScopeHelpInfo:
        """Returns an OptionScopeHelpInfo for the options parsed by the given parser."""

        basic_options = []
        advanced_options = []
        deprecated_options = []
        for args, kwargs in parser.option_registrations_iter():
            history = parser.history(kwargs["dest"])
            ohi = self.get_option_help_info(args, kwargs)
            ohi = dataclasses.replace(ohi, value_history=history)
            if ohi.deprecation_active:
                deprecated_options.append(ohi)
            elif kwargs.get("advanced"):
                advanced_options.append(ohi)
            else:
                basic_options.append(ohi)

        return OptionScopeHelpInfo(
            scope=self._scope,
            description=description,
            provider=provider,
            is_goal=is_goal,
            deprecated_scope=deprecated_scope,
            basic=tuple(basic_options),
            advanced=tuple(advanced_options),
            deprecated=tuple(deprecated_options),
        )

    def get_option_help_info(self, args, kwargs):
        """Returns an OptionHelpInfo for the option registered with the given (args, kwargs)."""
        display_args = []
        scoped_cmd_line_args = []
        unscoped_cmd_line_args = []

        for arg in args:
            is_short_arg = len(arg) == 2
            unscoped_cmd_line_args.append(arg)
            if self._scope_prefix:
                scoped_arg = f"--{self._scope_prefix}-{arg.lstrip('-')}"
            else:
                scoped_arg = arg
            scoped_cmd_line_args.append(scoped_arg)

            if Parser.is_bool(kwargs):
                if is_short_arg:
                    display_args.append(scoped_arg)
                else:
                    unscoped_cmd_line_args.append(f"--no-{arg[2:]}")
                    sa_2 = scoped_arg[2:]
                    scoped_cmd_line_args.append(f"--no-{sa_2}")
                    display_args.append(f"--[no-]{sa_2}")
            else:
                metavar = self.compute_metavar(kwargs)
                display_args.append(f"{scoped_arg}={metavar}")
                if kwargs.get("passthrough"):
                    type_str = self.stringify_type(kwargs.get("member_type", str))
                    display_args.append(f"... -- [{type_str} [{type_str} [...]]]")

        typ = kwargs.get("type", str)
        default = self.compute_default(**kwargs)
        help_msg = kwargs.get("help", "No help available.")
        deprecation_start_version = kwargs.get("deprecation_start_version")
        removal_version = kwargs.get("removal_version")
        deprecation_active = removal_version is not None and deprecated.is_deprecation_active(
            deprecation_start_version
        )
        deprecated_message = None
        if removal_version:
            deprecated_tense = deprecated.get_deprecated_tense(removal_version)
            message_start = (
                "Deprecated"
                if deprecation_active
                else f"Upcoming deprecation in version: {deprecation_start_version}"
            )
            deprecated_message = (
                f"{message_start}, {deprecated_tense} removed in version: {removal_version}."
            )
        removal_hint = kwargs.get("removal_hint")
        choices = self.compute_choices(kwargs)

        dest = Parser.parse_dest(*args, **kwargs)
        # Global options have three env var variants. The last one is the most human-friendly.
        env_var = Parser.get_env_var_names(self._scope, dest)[-1]

        target_field_name = f"{self._scope_prefix}_{option_field_name_for(args)}".replace("-", "_")
        environment_aware = kwargs.get("environment_aware") is True
        fromfile = kwargs.get("fromfile", False)

        ret = OptionHelpInfo(
            display_args=tuple(display_args),
            comma_separated_display_args=", ".join(display_args),
            scoped_cmd_line_args=tuple(scoped_cmd_line_args),
            unscoped_cmd_line_args=tuple(unscoped_cmd_line_args),
            env_var=env_var,
            config_key=dest,
            target_field_name=target_field_name if environment_aware else None,
            typ=typ,
            default=default,
            help=help_msg,
            deprecation_active=deprecation_active,
            deprecated_message=deprecated_message,
            removal_version=removal_version,
            removal_hint=removal_hint,
            choices=choices,
            comma_separated_choices=None if choices is None else ", ".join(choices),
            value_history=None,
            fromfile=fromfile,
        )
        return ret
