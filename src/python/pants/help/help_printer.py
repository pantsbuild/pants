# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import sys
import textwrap
from typing import Dict, Optional, cast

from colors import cyan, green
from typing_extensions import Literal

from pants.base.build_environment import pants_release, pants_version
from pants.engine.goal import GoalSubsystem
from pants.engine.rules import UnionMembership
from pants.goal.goal import Goal
from pants.help.help_formatter import HelpFormatter
from pants.help.scope_info_iterator import ScopeInfoIterator
from pants.option.arg_splitter import (
    GoalsHelp,
    HelpRequest,
    NoGoalHelp,
    OptionsHelp,
    UnknownGoalHelp,
    VersionHelp,
)
from pants.option.options import Options
from pants.option.scope import GLOBAL_SCOPE, ScopeInfo


class HelpPrinter:
    """Prints help to the console."""

    def __init__(
        self,
        *,
        options: Options,
        help_request: Optional[HelpRequest] = None,
        union_membership: UnionMembership,
    ) -> None:
        self._options = options
        self._help_request = help_request or self._options.help_request
        self._union_membership = union_membership
        self._use_color = sys.stdout.isatty()

    @property
    def bin_name(self) -> str:
        return cast(str, self._options.for_global_scope().pants_bin_name)

    def print_help(self) -> Literal[0, 1]:
        """Print help to the console."""

        def print_hint() -> None:
            print(f"Use `{self.bin_name} goals` to list goals.")
            print(f"Use `{self.bin_name} help` to get help.")

        if isinstance(self._help_request, VersionHelp):
            print(pants_version())
        elif isinstance(self._help_request, OptionsHelp):
            self._print_options_help()
        elif isinstance(self._help_request, GoalsHelp):
            self._print_goals_help()
        elif isinstance(self._help_request, UnknownGoalHelp):
            print("Unknown goals: {}".format(", ".join(self._help_request.unknown_goals)))
            print_hint()
            return 1
        elif isinstance(self._help_request, NoGoalHelp):
            print("No goals specified.")
            print_hint()
            return 1
        return 0

    def _print_goals_help(self) -> None:
        global_options = self._options.for_global_scope()
        goal_descriptions: Dict[str, str] = {}
        if global_options.v2:
            goal_scope_infos = [
                scope_info
                for scope_info in self._options.known_scope_to_info.values()
                if scope_info.category == ScopeInfo.GOAL
            ]
            for scope_info in goal_scope_infos:
                optionable_cls = scope_info.optionable_cls
                if optionable_cls is None or not issubclass(optionable_cls, GoalSubsystem):
                    continue
                is_implemented = self._union_membership.has_members_for_all(
                    optionable_cls.required_union_implementations
                )
                if not is_implemented:
                    continue
                description = scope_info.description or "<no description>"
                goal_descriptions[scope_info.scope] = description
        if global_options.v1:
            goal_descriptions.update(
                {goal.name: goal.description_first_line for goal in Goal.all() if goal.description}
            )

        title_text = "Goals"
        title = f"{title_text}\n{'-' * len(title_text)}"
        if self._use_color:
            title = green(title)

        max_width = max(len(name) for name in goal_descriptions.keys())
        chars_before_description = max_width + 2

        def format_goal(name: str, description: str) -> str:
            name = name.ljust(chars_before_description)
            if self._use_color:
                name = cyan(name)
            description_lines = textwrap.wrap(description, 80 - chars_before_description)
            if len(description_lines) > 1:
                description_lines = [
                    description_lines[0],
                    *(f"{' ' * chars_before_description}{line}" for line in description_lines[1:]),
                ]
            description = "\n".join(description_lines)
            return f"{name}{description}\n"

        lines = [
            f"\n{title}\n",
            f"Use `{self.bin_name} help $goal` to get help for a particular goal.",
            "\n",
            *(
                format_goal(name, description)
                for name, description in sorted(goal_descriptions.items())
            ),
        ]
        print("\n".join(lines))

    def _print_options_help(self) -> None:
        """Print a help screen.

        Assumes that self._help_request is an instance of OptionsHelp.

        Note: Ony useful if called after options have been registered.
        """

        help_request = cast(OptionsHelp, self._help_request)
        global_options = self._options.for_global_scope()

        if help_request.all_scopes:
            help_scopes = set(self._options.known_scope_to_info.keys())
        else:
            # The scopes explicitly mentioned by the user on the cmd line.
            help_scopes = set(self._options.scope_to_flags.keys()) - {GLOBAL_SCOPE}

        # If --v1 is enabled at all, don't use v2_help, even if --v2 is also enabled.
        v2_help = global_options.v2 and not global_options.v1

        scope_info_iterator = ScopeInfoIterator(
            scope_to_info=self._options.known_scope_to_info, v2_help=v2_help
        )

        scope_infos = list(scope_info_iterator.iterate(help_scopes))

        if scope_infos:
            for scope_info in scope_infos:
                help_str = self._format_help(scope_info, help_request.advanced)
                if help_str:
                    print(help_str)
            return
        else:
            print(pants_release())
            print("\nUsage:")
            print(
                f"  {self.bin_name} [option ...] [goal ...] [target/file ...]  Attempt the specified goals."
            )
            print(f"  {self.bin_name} help                                       Get help.")
            print(
                f"  {self.bin_name} help [goal]                                Get help for a goal."
            )
            print(
                f"  {self.bin_name} help-advanced                              Get help for global advanced options."
            )
            print(
                f"  {self.bin_name} help-advanced [goal]                       Get help for a goal's advanced options."
            )
            print(
                f"  {self.bin_name} help-all                                   Get help for all goals."
            )
            print(
                f"  {self.bin_name} goals                                      List all installed goals."
            )
            print("")
            print("  [file] can be:")
            print("     A path to a file.")
            print("     A path glob, such as '**/*.ext', in quotes to prevent shell expansion.")
            print("  [target] accepts two special forms:")
            print("    dir:  to include all targets in the specified directory.")
            print("    dir:: to include all targets found recursively under the directory.")
            print("\nFriendly docs:\n  http://pantsbuild.org/")

            print(
                self._format_help(ScopeInfo(GLOBAL_SCOPE, ScopeInfo.GLOBAL), help_request.advanced)
            )

    def _format_help(self, scope_info: ScopeInfo, show_advanced_and_deprecated: bool) -> str:
        """Return a help message for the options registered on this object.

        Assumes that self._help_request is an instance of OptionsHelp.

        :param scope_info: Scope of the options.
        """
        scope = scope_info.scope
        description = scope_info.description
        help_formatter = HelpFormatter(
            scope=scope,
            show_advanced=show_advanced_and_deprecated,
            show_deprecated=show_advanced_and_deprecated,
            color=self._use_color,
        )
        formatted_lines = help_formatter.format_options(
            scope, description, self._options.get_parser(scope).option_registrations_iter()
        )
        return "\n".join(formatted_lines)
