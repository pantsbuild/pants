# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import textwrap
from enum import Enum

from pants.help.help_info_extracter import OptionHelpInfo, OptionScopeHelpInfo, to_help_str
from pants.help.maybe_color import MaybeColor
from pants.option.ranked_value import Rank, RankedValue
from pants.util.docutil import bin_name, terminal_width
from pants.util.strutil import hard_wrap


class HelpFormatter(MaybeColor):
    def __init__(self, *, show_advanced: bool, show_deprecated: bool, color: bool) -> None:
        super().__init__(color=color)
        self._show_advanced = show_advanced
        self._show_deprecated = show_deprecated
        self._width = terminal_width()

    def format_options(self, oshi: OptionScopeHelpInfo) -> list[str]:
        """Return a help message for the specified options."""
        lines = []

        def add_option(ohis, *, category=None) -> None:
            lines.append("")
            goal_or_subsystem = "goal" if oshi.is_goal else "subsystem"
            display_scope = f"`{oshi.scope}` {goal_or_subsystem}" if oshi.scope else "Global"
            if category:
                title = f"{display_scope} {category} options"
                lines.append(self.maybe_green(f"{title}\n{'-' * len(title)}"))
            else:
                # The basic options section gets the description and options scope info.
                # No need to repeat those in the advanced section.
                title = f"{display_scope} options"
                lines.append(self.maybe_green(f"{title}\n{'-' * len(title)}\n"))
                lines.extend(hard_wrap(oshi.description, width=self._width))
                lines.append(" ")
                lines.append(f"Activated by {self.maybe_magenta(oshi.provider)}")
                config_section = f"[{oshi.scope or 'GLOBAL'}]"
                lines.append(f"Config section: {self.maybe_magenta(config_section)}")
            lines.append(" ")
            if not ohis:
                lines.append("None available.")
                return
            for ohi in ohis:
                lines.extend([*self.format_option(ohi), ""])

        add_option(oshi.basic)
        show_advanced = self._show_advanced or (not oshi.basic and oshi.advanced)
        if show_advanced:  # show advanced options if there are no basic ones.
            add_option(oshi.advanced, category="advanced")
        if self._show_deprecated and oshi.deprecated:
            add_option(oshi.deprecated, category="deprecated")
        if not show_advanced and oshi.advanced:
            lines.append(
                self.maybe_green(
                    f"Advanced options available. You can list them by running "
                    f"{bin_name()} help-advanced {oshi.scope}."
                )
            )
        return [*lines, ""]

    def format_option(self, ohi: OptionHelpInfo) -> list[str]:
        """Format the help output for a single option.

        :param ohi: Extracted information for option to print
        :return: Formatted help text for this option
        """

        def maybe_parens(s: str | None) -> str:
            return f" ({s})" if s else ""

        def format_value(ranked_val: RankedValue, prefix: str, left_padding: str) -> list[str]:
            if isinstance(ranked_val.value, (list, dict)):
                is_enum_list = (
                    isinstance(ranked_val.value, list)
                    and len(ranked_val.value) > 0
                    and isinstance(ranked_val.value[0], Enum)
                )
                normalized_val = (
                    [enum_elmt.value for enum_elmt in ranked_val.value]
                    if is_enum_list
                    else ranked_val.value
                )
                val_lines = json.dumps(normalized_val, sort_keys=True, indent=4).split("\n")
            else:
                val_lines = [to_help_str(ranked_val.value)]
            val_lines[0] = f"{prefix}{val_lines[0]}"
            val_lines[-1] = f"{val_lines[-1]}{maybe_parens(ranked_val.details)}"
            val_lines = [self.maybe_cyan(f"{left_padding}{line}") for line in val_lines]
            return val_lines

        def wrap(s: str) -> list[str]:
            return hard_wrap(s, indent=len(indent), width=self._width)

        indent = "      "

        arg_lines = [f"  {self.maybe_magenta(args)}" for args in ohi.display_args]
        arg_lines.append(self.maybe_magenta(f"  {ohi.env_var}"))
        arg_lines.append(self.maybe_magenta(f"  {ohi.config_key}"))

        choices = "" if ohi.choices is None else f"one of: [{', '.join(ohi.choices)}]"
        choices_lines = [
            f"{indent}{'  ' if i != 0 else ''}{self.maybe_cyan(s)}"
            for i, s in enumerate(textwrap.wrap(f"{choices}", self._width))
        ]

        deprecated_lines = []
        if ohi.deprecated_message:
            maybe_colorize = self.maybe_red if ohi.deprecation_active else self.maybe_yellow
            deprecated_lines.extend(wrap(maybe_colorize(ohi.deprecated_message)))
            if ohi.removal_hint:
                deprecated_lines.extend(wrap(maybe_colorize(ohi.removal_hint)))

        default_lines = format_value(RankedValue(Rank.HARDCODED, ohi.default), "default: ", indent)
        if not ohi.value_history:
            # Should never happen, but this keeps mypy happy.
            raise ValueError("No value history - options not parsed.")

        final_val = ohi.value_history.final_value
        curr_value_lines = format_value(final_val, "current value: ", indent)

        interesting_ranked_values = [
            rv
            for rv in reversed(ohi.value_history.ranked_values)
            if rv.rank not in (Rank.NONE, Rank.HARDCODED, final_val.rank)
        ]
        value_derivation_lines = [
            line
            for rv in interesting_ranked_values
            for line in format_value(rv, "overrode: ", f"{indent}    ")
        ]
        description_lines = wrap(ohi.help)
        if ohi.target_field_name:
            description_lines.extend(
                wrap(
                    f"\nCan be overriden by field `{ohi.target_field_name}` on "
                    "`local_environment`, `docker_environment`, or `remote_environment` targets."
                )
            )
        lines = [
            *arg_lines,
            *choices_lines,
            *default_lines,
            *curr_value_lines,
            *value_derivation_lines,
            *deprecated_lines,
            *description_lines,
        ]
        return lines
