# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import difflib
import json
import re
import textwrap
from itertools import cycle
from typing import Callable, Dict, Iterable, List, Literal, Optional, Set, Tuple, cast

from pants.base.build_environment import pants_version
from pants.help.help_formatter import HelpFormatter
from pants.help.help_info_extracter import AllHelpInfo, HelpJSONEncoder
from pants.help.help_tools import ToolHelpInfo
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
from pants.util.docutil import bin_name, terminal_width
from pants.util.strutil import first_paragraph, hard_wrap, pluralize, softwrap


class HelpPrinter(MaybeColor):
    """Prints general and goal-related help to the console."""

    def __init__(
        self,
        *,
        help_request: HelpRequest,
        all_help_info: AllHelpInfo,
        color: bool,
    ) -> None:
        super().__init__(color)
        self._help_request = help_request
        self._all_help_info = all_help_info
        self._width = terminal_width()
        self._reserved_names = {
            "api-types",
            "backends",
            "global",
            "goals",
            "subsystems",
            "symbols",
            "targets",
            "tools",
        }

    def print_help(self) -> Literal[0, 1]:
        """Print help to the console."""

        def print_hint() -> None:
            print(f"Use `{self.maybe_green(bin_name() + ' help')}` to get help.")
            print(f"Use `{self.maybe_green(bin_name() + ' help goals')}` to list goals.")

        if isinstance(self._help_request, VersionHelp):
            print(pants_version())
            return 0
        elif isinstance(self._help_request, AllHelp):
            self._print_all_help()
            return 0
        elif isinstance(self._help_request, ThingHelp):
            return self._print_thing_help()
        elif isinstance(self._help_request, UnknownGoalHelp):
            # Only print help and suggestions for the first unknown goal.
            # It gets confusing to try and show suggestions for multiple cases.
            unknown_goal = self._help_request.unknown_goals[0]
            print(f"Unknown goal: {self.maybe_red(unknown_goal)}")
            self._print_alternatives(unknown_goal, self._all_help_info.name_to_goal_info.keys())
            print_hint()
            return 1
        elif isinstance(self._help_request, NoGoalHelp):
            print("No goals specified.")
            print_hint()
            return 1
        else:
            # Unexpected.
            return 1

    def _print_alternatives(self, match: str, all_things: Iterable[str]) -> None:
        did_you_mean = difflib.get_close_matches(match, all_things)

        if did_you_mean:
            formatted_matches = self._format_did_you_mean_matches(did_you_mean)
            print(f"Did you mean {formatted_matches}?")

    def _print_title(self, title_text: str) -> None:
        title = self.maybe_green(f"{title_text}\n{'-' * len(title_text)}")
        print(f"\n{title}\n")

    def _print_table(self, table: Dict[str, Optional[str]]) -> None:
        longest_key = max(len(key) for key, value in table.items() if value is not None)
        for key, value in table.items():
            if value is None:
                continue
            print(
                self.maybe_cyan(f"{key:{longest_key}}:"),
                self.maybe_magenta(
                    f"\n{' ':{longest_key+2}}".join(
                        hard_wrap(value, width=self._width - longest_key - 2)
                    )
                ),
            )

    def _get_thing_help_table(self) -> Dict[str, Callable[[str, bool], None]]:
        def _help_table(
            things: Iterable[str], help_printer: Callable[[str, bool], None]
        ) -> Dict[str, Callable[[str, bool], None]]:
            return dict(zip(things, cycle((help_printer,))))

        top_level_help_items = _help_table(self._reserved_names, self._print_top_level_help)
        return {
            **top_level_help_items,
            **_help_table(self._all_help_info.scope_to_help_info.keys(), self._print_options_help),
            **_help_table(
                self._all_help_info.name_to_target_type_info.keys(), self._print_target_help
            ),
            **_help_table(self._symbol_names(include_targets=False), self._print_symbol_help),
            **_help_table(
                self._all_help_info.name_to_api_type_info.keys(), self._print_api_type_help
            ),
            **_help_table(self._all_help_info.name_to_rule_info.keys(), self._print_rule_help),
            **_help_table(
                self._all_help_info.env_var_to_help_info.keys(), self._print_env_var_help
            ),
        }

    @staticmethod
    def _disambiguate_things(
        things: Iterable[str], all_things: Iterable[str]
    ) -> Tuple[Set[str], Set[str]]:
        """Returns two sets of strings, one with disambiguated things and the second with
        unresolvable things."""
        disambiguated: Set[str] = set()
        unknown: Set[str] = set()

        for thing in things:
            # Look for typos and close matches first.
            alternatives = tuple(difflib.get_close_matches(thing, all_things))
            if len(alternatives) == 1 and thing in alternatives[0]:
                disambiguated.add(alternatives[0])
                continue

            # For api types and rules, see if we get a match, by ignoring the leading module path.
            found_things: List[str] = []
            suffix = f".{thing}"
            for known_thing in all_things:
                if known_thing.endswith(suffix):
                    found_things.append(known_thing)
            if len(found_things) == 1:
                disambiguated.add(found_things[0])
                continue

            unknown.add(thing)
        return disambiguated, unknown

    def _format_summary_description(self, descr: str, chars_before_description: int) -> str:
        lines = textwrap.wrap(descr, self._width - chars_before_description)
        if len(lines) > 1:
            lines = [
                lines[0],
                *(f"{' ' * chars_before_description}{line}" for line in lines[1:]),
            ]
        return "\n".join(lines)

    def _print_all_help(self) -> None:
        print(self._get_help_json())

    def _print_thing_help(self) -> Literal[0, 1]:
        """Print a help screen.

        Assumes that self._help_request is an instance of OptionsHelp.

        Note: Ony useful if called after options have been registered.
        """
        help_request = cast(ThingHelp, self._help_request)
        # API types may end up in `likely_specs`, so include them in things to get help for.
        things = set(help_request.things + help_request.likely_specs)
        help_table = self._get_thing_help_table()
        maybe_unknown_things = {thing for thing in things if thing not in help_table}
        disambiguated_things, unknown_things = self._disambiguate_things(
            maybe_unknown_things, help_table.keys()
        )
        things = things - maybe_unknown_things | disambiguated_things
        # Filter out likely specs from unknown things, as we don't want them to interfere.
        unknown_things -= set(help_request.likely_specs)

        if unknown_things:
            # Only print help and suggestions for the first unknown thing.
            # It gets confusing to try and show suggestions for multiple cases.
            thing = unknown_things.pop()
            print(self.maybe_red(f"Unknown entity: {thing}"))
            self._print_alternatives(
                thing,
                set(help_table.keys()) - self._reserved_names
                | {
                    canonical_name.rsplit(".", 1)[-1]
                    for canonical_name in help_table.keys()
                    if "." in canonical_name
                },
            )
            return 1

        if not things:
            self._print_global_help()
            return 0

        for thing in sorted(things):
            help_table[thing](thing, help_request.advanced)
        return 0

    def _print_top_level_help(self, thing: str, show_advanced: bool) -> None:
        if thing == "goals":
            self._print_all_goals()
        elif thing == "subsystems":
            self._print_all_subsystems()
        elif thing == "targets":
            self._print_all_targets()
        elif thing == "global":
            self._print_options_help(GLOBAL_SCOPE, show_advanced)
        elif thing == "tools":
            self._print_all_tools()
        elif thing == "api-types":
            self._print_all_api_types()
        elif thing == "backends":
            self._print_all_backends(show_advanced)
        elif thing == "symbols":
            self._print_all_symbols(show_advanced)

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
        specific_help_cmd = f"{bin_name()} help <goal>"
        print(
            softwrap(
                f"""
                Use `{self.maybe_green(specific_help_cmd)}` to get help for a specific goal. If
                you expect to see more goals listed, you may need to activate backends; run
                `{bin_name()} help backends`.
                """
            )
        )

    def _print_all_subsystems(self) -> None:
        self._print_title("Subsystems")

        subsystem_description: Dict[str, str] = {}
        for help_info in self._all_help_info.non_deprecated_option_scope_help_infos():
            if not help_info.is_goal and help_info.scope:
                subsystem_description[help_info.scope] = first_paragraph(help_info.description)

        longest_subsystem_alias = max(len(alias) for alias in subsystem_description.keys())
        chars_before_description = longest_subsystem_alias + 2
        for alias, description in sorted(subsystem_description.items()):
            alias = self.maybe_cyan(alias.ljust(chars_before_description))
            description = self._format_summary_description(description, chars_before_description)
            print(f"{alias}{description}\n")

        specific_help_cmd = f"{bin_name()} help $subsystem"
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
            if alias.startswith("_"):
                continue
            alias_str = self.maybe_cyan(f"{alias}".ljust(chars_before_description))
            summary = self._format_summary_description(
                target_type_info.summary, chars_before_description
            )
            print(f"{alias_str}{summary}\n")
        specific_help_cmd = f"{bin_name()} help $target_type"
        print(
            f"Use `{self.maybe_green(specific_help_cmd)}` to get help for a specific "
            f"target type.\n"
        )

    def _print_all_tools(self) -> None:
        self._print_title("External Tools")
        ToolHelpInfo.print_all(ToolHelpInfo.iter(self._all_help_info), self)
        tool_help_cmd = f"{bin_name()} help $tool"
        print(f"Use `{self.maybe_green(tool_help_cmd)}` to get help for a specific tool.\n")

    def _print_all_api_types(self) -> None:
        self._print_title("Plugin API Types")
        api_type_descriptions: Dict[str, Tuple[str, str]] = {}
        indent_api_summary = 0
        for api_info in self._all_help_info.name_to_api_type_info.values():
            name = api_info.name
            if name.startswith("_"):
                continue
            if api_info.is_union:
                name += " <union>"
            summary = (api_info.documentation or "").split("\n", 1)[0]
            api_type_descriptions[name] = (api_info.module, summary)
            indent_api_summary = max(indent_api_summary, len(name) + 2, len(api_info.module) + 2)

        for name, (module, summary) in api_type_descriptions.items():
            name = self.maybe_cyan(name.ljust(indent_api_summary))
            description_lines = hard_wrap(
                summary or " ", indent=indent_api_summary, width=self._width
            )
            # Juggle the description lines, to inject the api type module on the second line flushed
            # left just below the type name (potentially sharing the line with the second line of
            # the description that will be aligned to the right).
            if len(description_lines) > 1:
                # Place in front of the description line.
                description_lines[
                    1
                ] = f"{module:{indent_api_summary}}{description_lines[1][indent_api_summary:]}"
            else:
                # There is no second description line.
                description_lines.append(module)
            # All description lines are indented, but the first line should be indented by the api
            # type name, so we strip that.
            description_lines[0] = description_lines[0][indent_api_summary:]
            description = "\n".join(description_lines)
            print(f"{name}{description}\n")
        api_help_cmd = f"{bin_name()} help [api_type/rule_name]"
        print(
            f"Use `{self.maybe_green(api_help_cmd)}` to get help for a specific API type or rule.\n"
        )

    def _print_all_backends(self, include_experimental: bool) -> None:
        self._print_title("Backends")
        print(
            softwrap(
                """
                List with all known backends for Pants.

                Enabled backends are marked with `*`. To enable a backend add it to
                `[GLOBAL].backend_packages`.
                """
            ),
            "\n",
        )
        backends = self._all_help_info.name_to_backend_help_info
        provider_col_width = 3 + max(map(len, (info.provider for info in backends.values())))
        enabled_col_width = 4
        for info in backends.values():
            if not (include_experimental or info.enabled) and ".experimental." in info.name:
                continue
            enabled = "[*] " if info.enabled else "[ ] "
            name_col_width = max(
                len(info.name) + 1, self._width - enabled_col_width - provider_col_width
            )
            name = self.maybe_cyan(f"{info.name:{name_col_width}}")
            provider = self.maybe_magenta(info.provider) if info.enabled else info.provider
            print(f"{enabled}{name}[{provider}]")
            if info.description and self._width > 10:
                print(
                    "\n".join(
                        hard_wrap(
                            softwrap(info.description),
                            indent=enabled_col_width + 1,
                            width=self._width - enabled_col_width - 1,
                        )
                    )
                )

    def _symbol_names(self, include_targets: bool) -> Iterable[str]:
        return sorted(
            {
                symbol.name
                for symbol in self._all_help_info.name_to_build_file_info.values()
                if (include_targets or not symbol.is_target) and not re.match("_[^_]", symbol.name)
            }
        )

    def _print_all_symbols(self, include_targets: bool) -> None:
        self._print_title("BUILD file symbols")
        symbols = self._all_help_info.name_to_build_file_info
        names = self._symbol_names(include_targets)
        longest_symbol_name = max(len(name) for name in names)
        chars_before_description = longest_symbol_name + 2

        for name in sorted(names):
            name_str = self.maybe_cyan(f"{name}".ljust(chars_before_description))
            summary = self._format_summary_description(
                first_paragraph(symbols[name].documentation or ""), chars_before_description
            )
            print(f"{name_str}{summary}\n")

    def _print_global_help(self):
        def print_cmd(args: str, desc: str):
            cmd = self.maybe_green(f"{bin_name()} {args}".ljust(41))
            print(f"  {cmd}  {desc}")

        print(f"\nPants {pants_version()}")
        print("\nUsage:\n")
        print_cmd(
            "[options] [goals] [inputs]",
            "Attempt the specified goals on the specified inputs.",
        )
        print_cmd("help", "Display this usage message.")
        print_cmd("help goals", "List all installed goals.")
        print_cmd("help targets", "List all installed target types.")
        print_cmd("help subsystems", "List all configurable subsystems.")
        print_cmd("help tools", "List all external tools.")
        print_cmd("help backends", "List all available backends.")
        print_cmd("help-advanced backends", "List all backends, including experimental/preview.")
        print_cmd("help symbols", "List available BUILD file symbols.")
        print_cmd(
            "help-advanced symbols",
            "List all available BUILD file symbols, including target types.",
        )
        print_cmd("help api-types", "List all plugin API types.")
        print_cmd("help global", "Help for global options.")
        print_cmd("help-advanced global", "Help for global advanced options.")
        print_cmd(
            "help [name]",
            "Help for a target type, goal, subsystem, plugin API type or rule.",
        )
        print_cmd(
            "help-advanced [goal/subsystem]", "Help for a goal or subsystem's advanced options."
        )
        print_cmd("help-all", "Print a JSON object containing all help info.")

        print("")
        print("  [inputs] can be:")
        print(f"     A file, e.g. {self.maybe_cyan('path/to/file.ext')}")
        glob_str = self.maybe_cyan("'**/*.ext'")
        print(f"     A path glob, e.g. {glob_str} (in quotes to prevent premature shell expansion)")
        print(f"     A directory, e.g. {self.maybe_cyan('path/to/dir')}")
        print(
            f"     A directory ending in `::` to include all subdirectories, e.g. {self.maybe_cyan('path/to/dir::')}"
        )
        print(f"     A target address, e.g. {self.maybe_cyan('path/to/dir:target_name')}.")
        print(
            f"     Any of the above with a `-` prefix to ignore the value, e.g. {self.maybe_cyan('-path/to/ignore_me::')}"
        )

        print(f"\nDocumentation at {self.maybe_magenta('https://www.pantsbuild.org')}")
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

    def _print_target_help(self, target_alias: str, _: bool) -> None:
        self._print_title(f"`{target_alias}` target")
        tinfo = self._all_help_info.name_to_target_type_info[target_alias]
        if tinfo.description:
            formatted_desc = "\n".join(hard_wrap(tinfo.description, width=self._width))
            print(formatted_desc)
        print(f"\n\nActivated by {self.maybe_magenta(tinfo.provider)}")
        print("Valid fields:")
        for field in sorted(tinfo.fields, key=lambda x: (-x.required, x.alias)):
            print()
            print(self.maybe_magenta(field.alias))
            indent = "    "
            required_or_default = "required" if field.required else f"default: {field.default}"
            if field.provider not in ["", tinfo.provider]:
                print(self.maybe_cyan(f"{indent}from: {field.provider}"))
            print(self.maybe_cyan(f"{indent}type: {field.type_hint}"))
            print(self.maybe_cyan(f"{indent}{required_or_default}"))
            if field.description:
                formatted_desc = "\n".join(
                    hard_wrap(field.description, indent=len(indent), width=self._width)
                )
                print("\n" + formatted_desc)
        print()

    def _print_symbol_help(self, name: str, _: bool) -> None:
        self._print_title(f"`{name}` BUILD file symbol")
        symbol = self._all_help_info.name_to_build_file_info[name]
        if symbol.signature:
            print(self.maybe_magenta(f"Signature: {symbol.name}{symbol.signature}\n"))
        print("\n".join(hard_wrap(symbol.documentation or "Undocumented.", width=self._width)))

    def _print_api_type_help(self, name: str, show_advanced: bool) -> None:
        self._print_title(f"`{name}` api type")
        type_info = self._all_help_info.name_to_api_type_info[name]
        print("\n".join(hard_wrap(type_info.documentation or "Undocumented.", width=self._width)))
        print()
        self._print_table(
            {
                "activated by": type_info.provider,
                "union type": type_info.union_type,
                "union members": "\n".join(type_info.union_members) if type_info.is_union else None,
                "dependencies": "\n".join(type_info.dependencies) if show_advanced else None,
                "dependents": "\n".join(type_info.dependents) if show_advanced else None,
                f"returned by {pluralize(len(type_info.returned_by_rules), 'rule')}": "\n".join(
                    type_info.returned_by_rules
                )
                if show_advanced
                else None,
                f"consumed by {pluralize(len(type_info.consumed_by_rules), 'rule')}": "\n".join(
                    type_info.consumed_by_rules
                )
                if show_advanced
                else None,
                f"used in {pluralize(len(type_info.used_in_rules), 'rule')}": "\n".join(
                    type_info.used_in_rules
                )
                if show_advanced
                else None,
            }
        )
        print()
        if not show_advanced:
            print(
                self.maybe_green(
                    f"Include API types and rules dependency information by running "
                    f"`{bin_name()} help-advanced {name}`.\n"
                )
            )

    def _print_rule_help(self, rule_name: str, show_advanced: bool) -> None:
        rule = self._all_help_info.name_to_rule_info[rule_name]
        title = f"`{rule_name}` rule"
        self._print_title(title)
        if rule.description:
            print(rule.description + "\n")
        print("\n".join(hard_wrap(rule.documentation or "Undocumented.", width=self._width)))
        print()
        self._print_table(
            {
                "activated by": rule.provider,
                "returns": rule.output_type,
                f"takes {pluralize(len(rule.input_types), 'input')}": ", ".join(rule.input_types),
                f"awaits {pluralize(len(rule.input_gets), 'get')}": "\n".join(rule.input_gets)
                if show_advanced
                else None,
            }
        )
        print()

    def _print_env_var_help(self, env_var: str, show_advanced_and_deprecated: bool) -> None:
        ohi = self._all_help_info.env_var_to_help_info[env_var]
        help_formatter = HelpFormatter(
            show_advanced=show_advanced_and_deprecated,
            show_deprecated=show_advanced_and_deprecated,
            color=self.color,
        )
        for line in help_formatter.format_option(ohi):
            print(line)

        print()

    def _get_help_json(self) -> str:
        """Return a JSON object containing all the help info we have."""
        return json.dumps(
            self._all_help_info.asdict(), sort_keys=True, indent=2, cls=HelpJSONEncoder
        )
