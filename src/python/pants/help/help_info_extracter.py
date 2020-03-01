# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import inspect
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Type

from pants.base import deprecated
from pants.option.option_util import is_dict_option, is_list_option


@dataclass(frozen=True)
class OptionHelpInfo:
    """A container for help information for a single option.

    registering_class: The type that registered the option.
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
    choices: If this option has a constrained list of choices, a csv list of the choices.
    """

    registering_class: Type
    display_args: List[str]
    comma_separated_display_args: str
    scoped_cmd_line_args: List[str]
    unscoped_cmd_line_args: List[str]
    typ: Type
    default: str
    help: str
    deprecated_message: Optional[str]
    removal_version: Optional[str]
    removal_hint: Optional[str]
    choices: Optional[str]


@dataclass(frozen=True)
class OptionScopeHelpInfo:
    """A container for help information for a scope of options.

    scope: The scope of the described options.
    basic|advanced|deprecated: A list of OptionHelpInfo for the options in that group.
    """

    scope: str
    basic: List[OptionHelpInfo]
    advanced: List[OptionHelpInfo]
    deprecated: List[OptionHelpInfo]


class HelpInfoExtracter:
    """Extracts information useful for displaying help from option registration args."""

    @classmethod
    def get_option_scope_help_info_from_parser(cls, parser):
        """Returns a dict of help information for the options registered on the given parser.

        Callers can format this dict into cmd-line help, HTML or whatever.
        """
        return cls(parser.scope).get_option_scope_help_info(parser.option_registrations_iter())

    @staticmethod
    def compute_default(kwargs) -> str:
        """Compute the default val for help display for an option registered with these kwargs."""
        ranked_default = kwargs.get("default")
        typ = kwargs.get("type", str)

        default = ranked_default.value if ranked_default else None
        if default is None:
            return "None"

        if is_list_option(kwargs):
            member_typ = kwargs.get("member_type", str)

            def member_str(val):
                return f"'{val}'" if member_typ == str else f"{val}"

            default_str = (
                f"\"[{', '.join([member_str(val) for val in default])}]\"" if default else "[]"
            )
        elif is_dict_option(kwargs):
            if default:
                default_str = "{{ {} }}".format(
                    ", ".join(["'{}': {}".format(k, v) for k, v in default.items()])
                )
            else:
                default_str = "{}"
        elif typ == str:
            default_str = default.replace("\n", " ")
        elif inspect.isclass(typ) and issubclass(typ, Enum):
            default_str = default.value
        else:
            default_str = str(default)
        return default_str

    @staticmethod
    def compute_metavar(kwargs):
        """Compute the metavar to display in help for an option registered with these kwargs."""

        def stringify(t: Type) -> str:
            if t == dict:
                return "{'key1': val1, 'key2': val2, ...}"
            return f"<{t.__name__}>"

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
    def compute_choices(kwargs) -> Optional[str]:
        """Compute the option choices to display based on an Enum or list type."""
        typ = kwargs.get("type", [])
        if inspect.isclass(typ) and issubclass(typ, Enum):
            values = (choice.value for choice in typ)
        else:
            values = (str(choice) for choice in kwargs.get("choices", []))
        return ", ".join(values) or None

    def __init__(self, scope):
        self._scope = scope
        self._scope_prefix = scope.replace(".", "-")

    def get_option_scope_help_info(self, option_registrations_iter):
        """Returns an OptionScopeHelpInfo for the options registered with the (args, kwargs)
        pairs."""
        basic_options = []
        advanced_options = []
        deprecated_options = []
        # Sort the arguments, so we display the help in alphabetical order.
        for args, kwargs in sorted(option_registrations_iter):
            if kwargs.get("passive"):
                continue
            ohi = self.get_option_help_info(args, kwargs)
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
            basic=basic_options,
            advanced=advanced_options,
            deprecated=deprecated_options,
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
                scoped_arg = "--{}-{}".format(self._scope_prefix, arg.lstrip("-"))
            else:
                scoped_arg = arg
            scoped_cmd_line_args.append(scoped_arg)

            if kwargs.get("type") == bool:
                if is_short_arg:
                    display_args.append(scoped_arg)
                else:
                    unscoped_cmd_line_args.append("--no-{}".format(arg[2:]))
                    scoped_cmd_line_args.append("--no-{}".format(scoped_arg[2:]))
                    display_args.append("--[no-]{}".format(scoped_arg[2:]))
            else:
                metavar = self.compute_metavar(kwargs)
                display_args.append(f"{scoped_arg}={metavar}")

        typ = kwargs.get("type", str)
        default = self.compute_default(kwargs)
        help_msg = kwargs.get("help", "No help available.")
        removal_version = kwargs.get("removal_version")
        deprecated_message = None
        if removal_version:
            deprecated_tense = deprecated.get_deprecated_tense(removal_version)
            deprecated_message = "DEPRECATED. {} removed in version: {}".format(
                deprecated_tense, removal_version
            )
        removal_hint = kwargs.get("removal_hint")
        choices = self.compute_choices(kwargs)

        ret = OptionHelpInfo(
            registering_class=kwargs.get("registering_class", type(None)),
            display_args=display_args,
            comma_separated_display_args=", ".join(display_args),
            scoped_cmd_line_args=scoped_cmd_line_args,
            unscoped_cmd_line_args=unscoped_cmd_line_args,
            typ=typ,
            default=default,
            help=help_msg,
            deprecated_message=deprecated_message,
            removal_version=removal_version,
            removal_hint=removal_hint,
            choices=choices,
        )
        return ret
