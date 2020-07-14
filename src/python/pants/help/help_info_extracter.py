# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple, Type, cast

from pants.base import deprecated
from pants.engine.goal import GoalSubsystem
from pants.engine.unions import UnionMembership
from pants.option.option_util import is_dict_option, is_list_option
from pants.option.options import Options
from pants.option.parser import OptionValueHistory, Parser


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
    typ: Type
    default: Any
    default_str: str
    help: str
    deprecated_message: Optional[str]
    removal_version: Optional[str]
    removal_hint: Optional[str]
    choices: Optional[Tuple[str, ...]]
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


@dataclass(frozen=True)
class GoalHelpInfo:
    """A container for help information for a goal."""

    name: str
    description: str
    is_implemented: bool  # True iff all unions required by the goal are implemented.
    consumed_scopes: Tuple[str, ...]  # The scopes of subsystems consumed by this goal.


@dataclass(frozen=True)
class AllHelpInfo:
    """All available help info."""

    scope_to_help_info: Dict[str, OptionScopeHelpInfo]
    name_to_goal_info: Dict[str, GoalHelpInfo]


ConsumedScopesMapper = Callable[[str], Tuple[str, ...]]


class HelpInfoExtracter:
    """Extracts information useful for displaying help from option registration args."""

    @classmethod
    def get_all_help_info(
        cls,
        options: Options,
        union_membership: UnionMembership,
        consumed_scopes_mapper: ConsumedScopesMapper,
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

        return AllHelpInfo(
            scope_to_help_info=scope_to_help_info, name_to_goal_info=name_to_goal_info
        )

    @staticmethod
    def compute_default(**kwargs) -> Tuple[Any, str]:
        """Compute the default val for help display for an option registered with these kwargs.

        Returns a pair (default, stringified default suitable for display).
        """
        ranked_default = kwargs.get("default")
        typ = kwargs.get("type", str)

        if is_list_option(kwargs):
            default = ranked_default.value if ranked_default else []
            member_type = kwargs.get("member_type", str)
            if inspect.isclass(member_type) and issubclass(member_type, Enum):
                default = []

            def member_str(val):
                return f"'{val}'" if member_type == str else str(val)

            default_str = (
                f"\"[{', '.join(member_str(val) for val in default)}]\"" if default else "[]"
            )
        elif is_dict_option(kwargs):
            default = ranked_default.value if ranked_default else {}
            if default:
                items_str = ", ".join(f"'{k}': {v}" for k, v in default.items())
                default_str = f"{{ {items_str} }}"
            else:
                default_str = "{}"
        else:
            default = ranked_default.value if ranked_default else None
            default_str = str(default)

        if typ == str:
            default_str = default_str.replace("\n", " ")
        elif isinstance(default, Enum):
            default_str = default.value

        return default, default_str

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
        # Sort the arguments, so we display the help in alphabetical order.
        for args, kwargs in sorted(parser.option_registrations_iter()):
            if kwargs.get("passive"):
                continue
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
        default, default_str = self.compute_default(**kwargs)
        help_msg = kwargs.get("help", "No help available.")
        removal_version = kwargs.get("removal_version")
        deprecated_message = None
        if removal_version:
            deprecated_tense = deprecated.get_deprecated_tense(removal_version)
            deprecated_message = (
                f"DEPRECATED. {deprecated_tense} removed in version: {removal_version}"
            )
        removal_hint = kwargs.get("removal_hint")
        choices = self.compute_choices(kwargs)

        ret = OptionHelpInfo(
            display_args=tuple(display_args),
            comma_separated_display_args=", ".join(display_args),
            scoped_cmd_line_args=tuple(scoped_cmd_line_args),
            unscoped_cmd_line_args=tuple(unscoped_cmd_line_args),
            typ=typ,
            default=default,
            default_str=default_str,
            help=help_msg,
            deprecated_message=deprecated_message,
            removal_version=removal_version,
            removal_hint=removal_hint,
            choices=choices,
            value_history=None,
        )
        return ret
