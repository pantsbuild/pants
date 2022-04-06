# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import inspect
import json
from dataclasses import dataclass
from enum import Enum
from itertools import groupby
from typing import Any, Callable, Iterable, Optional, Tuple, Type, Union, cast, get_type_hints

from pants.base import deprecated
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.goal import GoalSubsystem
from pants.engine.rules import TaskRule
from pants.engine.target import Field, RegisteredTargetTypes, StringField, Target, TargetGenerator
from pants.engine.unions import UnionMembership, UnionRule
from pants.option.option_util import is_dict_option, is_list_option
from pants.option.options import Options
from pants.option.parser import OptionValueHistory, Parser
from pants.option.scope import ScopeInfo
from pants.util.frozendict import LazyFrozenDict
from pants.util.strutil import first_paragraph


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

    typ: The type of the option.
    default: The value of this option if no flags are specified (derived from config and env vars).
    help: The help message registered for this option.
    deprecated_message: If deprecated: A message explaining that this option is deprecated at
                        removal_version.
    removal_version: If deprecated: The version at which this option is to be removed.
    removal_hint: If deprecated: The removal hint message registered for this option.
    choices: If this option has a constrained set of choices, a tuple of the stringified choices.
    """

    display_args: tuple[str, ...]
    comma_separated_display_args: str
    scoped_cmd_line_args: tuple[str, ...]
    unscoped_cmd_line_args: tuple[str, ...]
    env_var: str
    config_key: str
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
            description=field.help,
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
        return cls(
            alias=target_type.alias,
            provider=provider,
            summary=first_paragraph(target_type.help),
            description=target_type.help,
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


@dataclass(frozen=True)
class RuleInfo:
    name: str
    description: str | None
    help: str | None
    provider: str
    input_types: tuple[str, ...]
    input_gets: tuple[str, ...]
    output_type: str
    output_desc: str | None


@dataclass(frozen=True)
class AllHelpInfo:
    """All available help info."""

    scope_to_help_info: LazyFrozenDict[str, OptionScopeHelpInfo]
    name_to_goal_info: LazyFrozenDict[str, GoalHelpInfo]
    name_to_target_type_info: LazyFrozenDict[str, TargetTypeHelpInfo]
    rule_output_type_to_rule_infos: LazyFrozenDict[str, tuple[RuleInfo, ...]]

    def non_deprecated_option_scope_help_infos(self):
        for oshi in self.scope_to_help_info.values():
            if not oshi.is_deprecated_scope():
                yield oshi

    def asdict(self) -> dict[str, Any]:
        return {
            field: {
                thing: (
                    tuple(dataclasses.asdict(t) for t in info)
                    if isinstance(info, tuple)
                    else dataclasses.asdict(info)
                )
                for thing, info in value.items()
            }
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
                        build_configuration.subsystem_to_providers.get(subsystem_cls)
                    )
                return HelpInfoExtracter(scope_info.scope).get_option_scope_help_info(
                    scope_info.description,
                    options.get_parser(scope_info.scope),
                    scope_info.is_goal,
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
                        build_configuration.subsystem_to_providers.get(subsystem_cls)
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
                        or None
                    ),
                    get_field_type_provider=lambda field_type: cls.get_provider(
                        build_configuration.union_rule_to_providers.get(
                            UnionRule(target_type._plugin_field_cls, field_type)
                        )
                        if build_configuration is not None
                        else None
                    ),
                )

            return load

        known_scope_infos = sorted(options.known_scope_to_info.values(), key=lambda x: x.scope)
        scope_to_help_info = LazyFrozenDict(
            {
                scope_info.scope: option_scope_help_info_loader_for(scope_info)
                for scope_info in known_scope_infos
                if not scope_info.scope.startswith("_")
            }
        )

        name_to_goal_info = LazyFrozenDict(
            {
                scope_info.scope: goal_help_info_loader_for(scope_info)
                for scope_info in known_scope_infos
                if scope_info.is_goal and not scope_info.scope.startswith("_")
            }
        )

        name_to_target_type_info = LazyFrozenDict(
            {
                alias: target_type_info_for(target_type)
                for alias, target_type in registered_target_types.aliases_to_types.items()
                if (
                    not alias.startswith("_")
                    and target_type.removal_version is None
                    and alias != target_type.deprecated_alias
                )
            }
        )

        return AllHelpInfo(
            scope_to_help_info=scope_to_help_info,
            name_to_goal_info=name_to_goal_info,
            name_to_target_type_info=name_to_target_type_info,
            rule_output_type_to_rule_infos=cls.get_rule_infos(build_configuration),
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

        stringify = lambda t: HelpInfoExtracter.stringify_type(t)

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
    def get_provider(providers: tuple[str, ...] | None) -> str:
        if not providers:
            return ""
        # Pick the shortest backend name.
        return sorted(providers, key=len)[0]

    @staticmethod
    def maybe_cleandoc(doc: str | None) -> str | None:
        return doc and inspect.cleandoc(doc)

    @staticmethod
    def rule_info_output_type(rule_info: RuleInfo) -> str:
        return rule_info.output_type

    @classmethod
    def get_rule_infos(
        cls, build_configuration: BuildConfiguration | None
    ) -> LazyFrozenDict[str, tuple[RuleInfo, ...]]:
        if build_configuration is None:
            return LazyFrozenDict({})

        rule_infos = [
            RuleInfo(
                name=rule.canonical_name,
                description=rule.desc,
                help=cls.maybe_cleandoc(rule.func.__doc__),
                provider=cls.get_provider(providers),
                input_types=tuple(selector.__name__ for selector in rule.input_selectors),
                input_gets=tuple(str(constraints) for constraints in rule.input_gets),
                output_type=rule.output_type.__name__,
                output_desc=cls.maybe_cleandoc(rule.output_type.__doc__),
            )
            for rule, providers in build_configuration.rule_to_providers.items()
            if isinstance(rule, TaskRule)
        ]

        def _capture(t: Iterable[RuleInfo]) -> Callable[[], tuple[RuleInfo, ...]]:
            # The `t` value from `groupby` is only live for the duration of the current for-loop
            # iteration, so we capture the data here now.
            data = tuple(t)

            def load() -> tuple[RuleInfo, ...]:
                return data

            return load

        return LazyFrozenDict(
            {
                rule_output_type: _capture(infos)
                for rule_output_type, infos in groupby(
                    sorted(rule_infos, key=cls.rule_info_output_type), key=cls.rule_info_output_type
                )
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

        ret = OptionHelpInfo(
            display_args=tuple(display_args),
            comma_separated_display_args=", ".join(display_args),
            scoped_cmd_line_args=tuple(scoped_cmd_line_args),
            unscoped_cmd_line_args=tuple(unscoped_cmd_line_args),
            env_var=env_var,
            config_key=dest,
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
        )
        return ret
