# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import difflib
import json
import textwrap
from typing import Dict, cast

from typing_extensions import Literal

from pants.base.build_environment import pants_version
from pants.help.help_formatter import HelpFormatter
from pants.help.help_info_extracter import AllHelpInfo, HelpJSONEncoder
from pants.help.maybe_color import MaybeColor
from pants.option.arg_splitter import (
    AllHelp,
    HelpRequest,
    NoGoalHelp,
    ThingHelp,
    UnknownGoalHelp,
    VersionHelp,
)
from pants.option.scope import GLOBAL_SCOPE
from pants.util.docutil import terminal_width
from pants.util.strutil import first_paragraph, hard_wrap


class HelpPrinter(MaybeColor):
    """Prints general and goal-related help to the console."""

    def __init__(
        self,
        *,
        bin_name: str,
        help_request: HelpRequest,
        all_help_info: AllHelpInfo,
        color: bool,
    ) -> None:
        super().__init__(color)
        self._bin_name = bin_name
        self._help_request = help_request
        self._all_help_info = all_help_info
        self._width = terminal_width()

    def print_help(self) -> Literal[0, 1]:
        """Print help to the console."""

        def print_hint() -> None:
            print(f"Use `{self.maybe_green(self._bin_name + ' help')}` to get help.")
            print(f"Use `{self.maybe_green(self._bin_name + ' help goals')}` to list goals.")

        if isinstance(self._help_request, VersionHelp):
            print(pants_version())
        elif isinstance(self._help_request, AllHelp):
            self._print_all_help()
        elif isinstance(self._help_request, ThingHelp):
            self._print_thing_help()
        elif isinstance(self._help_request, UnknownGoalHelp):
            # Only print help and suggestions for the first unknown goal.
            # It gets confusing to try and show suggestions for multiple cases.
            unknown_goal = self._help_request.unknown_goals[0]
            print(f"Unknown goal: {self.maybe_red(unknown_goal)}")

            did_you_mean = list(
                difflib.get_close_matches(
                    unknown_goal, self._all_help_info.name_to_goal_info.keys()
                )
            )

            if did_you_mean:
                formatted_matches = self._format_did_you_mean_matches(did_you_mean)
                print(f"Did you mean {formatted_matches}?")

            print_hint()
            return 1
        elif isinstance(self._help_request, NoGoalHelp):
            print("No goals specified.")
            print_hint()
            return 1
        return 0

    def _print_title(self, title_text: str) -> None:
        title = self.maybe_green(f"{title_text}\n{'-' * len(title_text)}")
        print(f"\n{title}\n")

    def _print_all_help(self) -> None:
        print(self._get_help_json())

    def _print_thing_help(self) -> None:
        """Print a help screen.

        Assumes that self._help_request is an instance of OptionsHelp.

        Note: Ony useful if called after options have been registered.
        """
        help_request = cast(ThingHelp, self._help_request)
        things = set(help_request.things)

        if things:
            for thing in sorted(things):
                if thing == "goals":
                    self._print_all_goals()
                elif thing == "subsystems":
                    self._print_all_subsystems()
                elif thing == "targets":
                    self._print_all_targets()
                elif thing == "global":
                    self._print_options_help(GLOBAL_SCOPE, help_request.advanced)
                elif thing in self._all_help_info.scope_to_help_info:
                    self._print_options_help(thing, help_request.advanced)
                elif thing in self._all_help_info.name_to_target_type_info:
                    self._print_target_help(thing)
                else:
                    print(self.maybe_red(f"Unknown entity: {thing}"))
        else:
            self._print_global_help()

    def _format_summary_description(self, descr: str, chars_before_description: int) -> str:
        lines = textwrap.wrap(descr, self._width - chars_before_description)
        if len(lines) > 1:
            lines = [
                lines[0],
                *(f"{' ' * chars_before_description}{line}" for line in lines[1:]),
            ]
        return "\n".join(lines)

    def _print_all_goals(self) -> None:
        goal_descriptions: Dict[str, str] = {}

        for goal_info in self._all_help_info.name_to_goal_info.values():
            if goal_info.is_implemented:
                goal_descriptions[goal_info.name] = goal_info.description

        self._print_title("Goals")

        max_width = max((len(name) for name in goal_descriptions.keys()), default=0)
        chars_before_description = max_width + 2

        def format_goal(name: str, descr: str) -> str:
            name = self.maybe_cyan(name.ljust(chars_before_description))
            descr = self._format_summary_description(descr, chars_before_description)
            return f"{name}{descr}\n"

        for name, description in sorted(goal_descriptions.items()):
            print(format_goal(name, first_paragraph(description)))
        specific_help_cmd = f"{self._bin_name} help $goal"
        print(f"Use `{self.maybe_green(specific_help_cmd)}` to get help for a specific goal.\n")

    def _print_all_subsystems(self) -> None:
        self._print_title("Subsystems")

        subsystem_description: Dict[str, str] = {}
        for alias, help_info in self._all_help_info.scope_to_help_info.items():
            if not help_info.is_goal and alias:
                subsystem_description[alias] = first_paragraph(help_info.description)

        longest_subsystem_alias = max(len(alias) for alias in subsystem_description.keys())
        chars_before_description = longest_subsystem_alias + 2
        for alias, description in sorted(subsystem_description.items()):
            alias = self.maybe_cyan(alias.ljust(chars_before_description))
            description = self._format_summary_description(description, chars_before_description)
            print(f"{alias}{description}\n")

        specific_help_cmd = f"{self._bin_name} help $subsystem"
        print(
            f"Use `{self.maybe_green(specific_help_cmd)}` to get help for a "
            f"specific subsystem.\n"
        )

    def _print_all_targets(self) -> None:
        self._print_title("Target types")

        longest_target_alias = max(
            len(alias) for alias in self._all_help_info.name_to_target_type_info.keys()
        )
        chars_before_description = longest_target_alias + 2
        for alias, target_type_info in sorted(
            self._all_help_info.name_to_target_type_info.items(), key=lambda x: x[0]
        ):
            alias_str = self.maybe_cyan(f"{alias}".ljust(chars_before_description))
            summary = self._format_summary_description(
                target_type_info.summary, chars_before_description
            )
            print(f"{alias_str}{summary}\n")
        specific_help_cmd = f"{self._bin_name} help $target_type"
        print(
            f"Use `{self.maybe_green(specific_help_cmd)}` to get help for a specific "
            f"target type.\n"
        )

    def _print_global_help(self):
        def print_cmd(args: str, desc: str):
            cmd = self.maybe_green(f"{self._bin_name} {args}".ljust(50))
            print(f"  {cmd}  {desc}")

        print(f"\nPants {pants_version()}")
        print("\nUsage:\n")
        print_cmd(
            "[option ...] [goal ...] [file/target ...]",
            "Attempt the specified goals on the specified files/targets.",
        )
        print_cmd("help", "Display this usage message.")
        print_cmd("help goals", "List all installed goals.")
        print_cmd("help targets", "List all installed target types.")
        print_cmd("help subsystems", "List all configurable subsystems.")
        print_cmd("help global", "Help for global options.")
        print_cmd("help-advanced global", "Help for global advanced options.")
        print_cmd("help [target_type/goal/subsystem]", "Help for a target type, goal or subsystem.")
        print_cmd(
            "help-advanced [goal/subsystem]", "Help for a goal or subsystem's advanced options."
        )
        print_cmd("help-all", "Print a JSON object containing all help info.")

        print("")
        print("  [file] can be:")
        print(f"     {self.maybe_cyan('path/to/file.ext')}")
        glob_str = self.maybe_cyan("'**/*.ext'")
        print(
            f"     A path glob, such as {glob_str}, in quotes to prevent premature shell expansion."
        )
        print("\n  [target] can be:")
        print(f"    {self.maybe_cyan('path/to/dir:target_name')}.")
        print(
            f"    {self.maybe_cyan('path/to/dir')} for a target whose name is the same as the directory name."
        )
        print(
            f"    {self.maybe_cyan('path/to/dir:')}  to include all targets in the specified directory."
        )
        print(
            f"    {self.maybe_cyan('path/to/dir::')} to include all targets found recursively under the directory.\n"
        )
        print(f"Documentation at {self.maybe_magenta('https://www.pantsbuild.org')}")
        pypi_url = f"https://pypi.org/pypi/pantsbuild.pants/{pants_version()}"
        print(f"Download at {self.maybe_magenta(pypi_url)}")

    def _print_options_help(self, scope: str, show_advanced_and_deprecated: bool) -> None:
        """Prints a human-readable help message for the options registered on this object.

        Assumes that self._help_request is an instance of OptionsHelp.
        """
        help_formatter = HelpFormatter(
            show_advanced=show_advanced_and_deprecated,
            show_deprecated=show_advanced_and_deprecated,
            color=self.color,
        )
        oshi = self._all_help_info.scope_to_help_info.get(scope)
        if not oshi:
            return
        formatted_lines = help_formatter.format_options(oshi)
        goal_info = self._all_help_info.name_to_goal_info.get(scope)
        if goal_info:
            related_scopes = sorted(set(goal_info.consumed_scopes) - {GLOBAL_SCOPE, goal_info.name})
            if related_scopes:
                related_subsystems_label = self.maybe_green("Related subsystems:")
                formatted_lines.append(f"{related_subsystems_label} {', '.join(related_scopes)}")
                formatted_lines.append("")
        for line in formatted_lines:
            print(line)

    def _print_target_help(self, target_alias: str) -> None:
        self._print_title(target_alias)
        tinfo = self._all_help_info.name_to_target_type_info[target_alias]
        if tinfo.description:
            formatted_desc = "\n".join(hard_wrap(tinfo.description, width=self._width))
            print(formatted_desc)
        print("\n\nValid fields:")
        for field in sorted(tinfo.fields, key=lambda x: x.alias):
            print()
            print(self.maybe_magenta(field.alias))
            indent = "    "
            required_or_default = "required" if field.required else f"default: {field.default}"
            print(self.maybe_cyan(f"{indent}type: {field.type_hint}"))
            print(self.maybe_cyan(f"{indent}{required_or_default}"))
            if field.description:
                formatted_desc = "\n".join(
                    hard_wrap(field.description, indent=len(indent), width=self._width)
                )
                print(formatted_desc)
        print()

    def _get_help_json(self) -> str:
        """Return a JSON object containing all the help info we have, for every scope."""
        return json.dumps(
            dataclasses.asdict(self._all_help_info), sort_keys=True, indent=2, cls=HelpJSONEncoder
        )
