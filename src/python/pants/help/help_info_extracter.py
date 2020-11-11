# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import inspect
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Generic, List, Optional, Tuple, Type, cast, get_type_hints

from pants.base import deprecated
from pants.engine.goal import GoalSubsystem
from pants.engine.target import (
    AsyncField,
    BoolField,
    DictStringToStringField,
    DictStringToStringSequenceField,
    Field,
    FloatField,
    IntField,
    PrimitiveField,
    RegisteredTargetTypes,
    ScalarField,
    SequenceField,
    StringField,
    StringOrStringSequenceField,
    StringSequenceField,
    Target,
)
from pants.engine.unions import UnionMembership
from pants.option.option_util import is_dict_option, is_list_option
from pants.option.options import Options
from pants.option.parser import OptionValueHistory, Parser
from pants.util.objects import get_docstring, get_docstring_summary, pretty_print_type_hint


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

    display_args: Tuple[str, ...]
    comma_separated_display_args: str
    scoped_cmd_line_args: Tuple[str, ...]
    unscoped_cmd_line_args: Tuple[str, ...]
    env_var: str
    config_key: str
    typ: Type
    default: Any
    help: str
    deprecated_message: Optional[str]
    removal_version: Optional[str]
    removal_hint: Optional[str]
    choices: Optional[Tuple[str, ...]]
    comma_separated_choices: Optional[str]
    value_history: Optional[OptionValueHistory]


@dataclass(frozen=True)
class OptionScopeHelpInfo:
    """A container for help information for a scope of options.

    scope: The scope of the described options.
    basic|advanced|deprecated: A list of OptionHelpInfo for the options in that group.
    """

    scope: str
    description: str
    is_goal: bool  # True iff the scope belongs to a GoalSubsystem.
    basic: Tuple[OptionHelpInfo, ...]
    advanced: Tuple[OptionHelpInfo, ...]
    deprecated: Tuple[OptionHelpInfo, ...]

    def collect_unscoped_flags(self) -> List[str]:
        flags: List[str] = []
        for options in (self.basic, self.advanced, self.deprecated):
            for ohi in options:
                flags.extend(ohi.unscoped_cmd_line_args)
        return flags

    def collect_scoped_flags(self) -> List[str]:
        flags: List[str] = []
        for options in (self.basic, self.advanced, self.deprecated):
            for ohi in options:
                flags.extend(ohi.scoped_cmd_line_args)
        return flags


@dataclass(frozen=True)
class GoalHelpInfo:
    """A container for help information for a goal."""

    name: str
    description: str
    is_implemented: bool  # True iff all unions required by the goal are implemented.
    consumed_scopes: Tuple[str, ...]  # The scopes of subsystems consumed by this goal.


@dataclass(frozen=True)
class TargetFieldHelpInfo:
    """A container for help information for a field in a target type."""

    alias: str
    description: Optional[str]
    type_hint: str
    required: bool
    default: Optional[str]

    @classmethod
    def create(cls, field: Type[Field]) -> "TargetFieldHelpInfo":
        # NB: It is very common (and encouraged) to subclass Fields to give custom behavior, e.g.
        # `PythonSources` subclassing `Sources`. Here, we set `fallback_to_ancestors=True` so that
        # we can still generate meaningful documentation for all these custom fields without
        # requiring the Field author to rewrite the docstring.
        #
        # However, if the original `Field` author did not define docstring, then this means we
        # would typically fall back to the docstring for `AsyncField`, `PrimitiveField`, or a
        # helper class like `StringField`. This is a quirk of this heuristic and it's not
        # intentional since these core `Field` types have documentation oriented to the custom
        # `Field` author and not the end user filling in fields in a BUILD file target.
        description = get_docstring(
            field,
            flatten=True,
            fallback_to_ancestors=True,
            ignored_ancestors={
                *Field.mro(),
                AsyncField,
                PrimitiveField,
                BoolField,
                DictStringToStringField,
                DictStringToStringSequenceField,
                FloatField,
                Generic,  # type: ignore[arg-type]
                IntField,
                ScalarField,
                SequenceField,
                StringField,
                StringOrStringSequenceField,
                StringSequenceField,
            },
        )
        if issubclass(field, PrimitiveField):
            raw_value_type = get_type_hints(field.compute_value)["raw_value"]
        elif issubclass(field, AsyncField):
            raw_value_type = get_type_hints(field.sanitize_raw_value)["raw_value"]
        else:
            raw_value_type = get_type_hints(field.__init__)["raw_value"]
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
            description=description,
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
    summary: Optional[str]
    description: Optional[str]
    fields: Tuple[TargetFieldHelpInfo, ...]

    @classmethod
    def create(
        cls, target_type: Type[Target], *, union_membership: UnionMembership
    ) -> "TargetTypeHelpInfo":
        return cls(
            alias=target_type.alias,
            summary=get_docstring_summary(target_type),
            description=get_docstring(target_type),
            fields=tuple(
                TargetFieldHelpInfo.create(field)
                for field in target_type.class_field_types(union_membership=union_membership)
                if not field.alias.startswith("_") and field.deprecated_removal_version is None
            ),
        )


@dataclass(frozen=True)
class AllHelpInfo:
    """All available help info."""

    scope_to_help_info: Dict[str, OptionScopeHelpInfo]
    name_to_goal_info: Dict[str, GoalHelpInfo]
    name_to_target_type_info: Dict[str, TargetTypeHelpInfo]


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
    ) -> AllHelpInfo:
        scope_to_help_info = {}
        name_to_goal_info = {}
        for scope_info in sorted(options.known_scope_to_info.values(), key=lambda x: x.scope):
            options.for_scope(scope_info.scope)  # Force parsing.
            optionable_cls = scope_info.optionable_cls
            if not scope_info.description:
                cls_name = (
                    f"{optionable_cls.__module__}.{optionable_cls.__qualname__}"
                    if optionable_cls
                    else ""
                )
                raise ValueError(
                    f"Subsystem {cls_name} with scope `{scope_info.scope}` has no description. "
                    f"Add a docstring or implement get_description()."
                )
            is_goal = optionable_cls is not None and issubclass(optionable_cls, GoalSubsystem)
            oshi: OptionScopeHelpInfo = HelpInfoExtracter(
                scope_info.scope
            ).get_option_scope_help_info(
                scope_info.description, options.get_parser(scope_info.scope), is_goal
            )
            scope_to_help_info[oshi.scope] = oshi

            if is_goal:
                goal_subsystem_cls = cast(Type[GoalSubsystem], optionable_cls)
                is_implemented = union_membership.has_members_for_all(
                    goal_subsystem_cls.required_union_implementations
                )
                name_to_goal_info[scope_info.scope] = GoalHelpInfo(
                    goal_subsystem_cls.name,
                    scope_info.description,
                    is_implemented,
                    consumed_scopes_mapper(scope_info.scope),
                )

        name_to_target_type_info = {
            alias: TargetTypeHelpInfo.create(target_type, union_membership=union_membership)
            for alias, target_type in registered_target_types.aliases_to_types.items()
            if not alias.startswith("_") and target_type.deprecated_removal_version is None
        }

        return AllHelpInfo(
            scope_to_help_info=scope_to_help_info,
            name_to_goal_info=name_to_goal_info,
            name_to_target_type_info=name_to_target_type_info,
        )

    @staticmethod
    def compute_default(**kwargs) -> Any:
        """Compute the default val for help display for an option registered with these kwargs.

        Returns a pair (default, stringified default suitable for display).
        """
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
    def stringify_type(t: Type) -> str:
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
    def compute_choices(kwargs) -> Optional[Tuple[str, ...]]:
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

    def __init__(self, scope: str):
        self._scope = scope
        self._scope_prefix = scope.replace(".", "-")

    def get_option_scope_help_info(self, description: str, parser: Parser, is_goal: bool):
        """Returns an OptionScopeHelpInfo for the options parsed by the given parser."""

        basic_options = []
        advanced_options = []
        deprecated_options = []
        for args, kwargs in parser.option_registrations_iter():
            history = parser.history(kwargs["dest"])
            ohi = self.get_option_help_info(args, kwargs)
            ohi = dataclasses.replace(ohi, value_history=history)
            if kwargs.get("removal_version"):
                deprecated_options.append(ohi)
            elif kwargs.get("advanced") or (
                kwargs.get("recursive") and not kwargs.get("recursive_root")
            ):
                # In order to keep the regular help output uncluttered, we treat recursive
                # options as advanced.  The concept of recursive options is not widely used
                # and not clear to the end user, so it's best not to expose it as a concept.
                advanced_options.append(ohi)
            else:
                basic_options.append(ohi)

        return OptionScopeHelpInfo(
            scope=self._scope,
            description=description,
            is_goal=is_goal,
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

            if kwargs.get("type") == bool:
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
        removal_version = kwargs.get("removal_version")
        deprecated_message = None
        if removal_version:
            deprecated_tense = deprecated.get_deprecated_tense(removal_version)
            deprecated_message = (
                f"Deprecated, {deprecated_tense} removed in version: {removal_version}"
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
            deprecated_message=deprecated_message,
            removal_version=removal_version,
            removal_hint=removal_hint,
            choices=choices,
            comma_separated_choices=None if choices is None else ", ".join(choices),
            value_history=None,
        )
        return ret
