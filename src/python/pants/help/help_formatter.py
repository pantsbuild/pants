# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import wrap
from typing import List, Optional

from colors import cyan, green, magenta, red

from pants.help.help_info_extracter import OptionHelpInfo, OptionScopeHelpInfo
from pants.option.ranked_value import Rank


class HelpFormatter:
    def __init__(self, *, show_advanced: bool, show_deprecated: bool, color: bool) -> None:
        self._show_advanced = show_advanced
        self._show_deprecated = show_deprecated
        self._color = color

    def _maybe_cyan(self, s):
        return self._maybe_color(cyan, s)

    def _maybe_green(self, s):
        return self._maybe_color(green, s)

    def _maybe_red(self, s):
        return self._maybe_color(red, s)

    def _maybe_magenta(self, s):
        return self._maybe_color(magenta, s)

    def _maybe_color(self, color, s):
        return color(s) if self._color else s

    def format_options(self, oshi: OptionScopeHelpInfo):
        """Return a help message for the specified options."""
        lines = []

        def add_option(ohis, *, category=None):
            lines.append("")
            display_scope = f"`{oshi.scope}`" if oshi.scope else "Global"
            if category:
                title = f"{display_scope} {category} options"
                lines.append(self._maybe_green(f"{title}\n{'-' * len(title)}"))
            else:
                title = f"{display_scope} options"
                lines.append(self._maybe_green(f"{title}\n{'-' * len(title)}"))
                if oshi.description:
                    lines.append(f"\n{oshi.description}")
            lines.append(" ")
            if not ohis:
                lines.append("No options available.")
                return
            for ohi in ohis:
                lines.extend([*self.format_option(ohi), ""])

        add_option(oshi.basic)
        if self._show_advanced:
            add_option(oshi.advanced, category="advanced")
        if self._show_deprecated:
            add_option(oshi.deprecated, category="deprecated")
        return [*lines, "\n"]

    def format_option(self, ohi: OptionHelpInfo) -> List[str]:
        """Format the help output for a single option.

        :param ohi: Extracted information for option to print
        :return: Formatted help text for this option
        """

        def maybe_parens(s: Optional[str]) -> str:
            return f" ({s})" if s else ""

        indent = "      "
        arg_lines = [f"  {self._maybe_magenta(args)}" for args in ohi.display_args]
        choices = "" if ohi.choices is None else f"one of: [{', '.join(ohi.choices)}]"
        choices_lines = [
            f"{indent}{'  ' if i != 0 else ''}{self._maybe_cyan(s)}"
            for i, s in enumerate(wrap(f"{choices}", 80))
        ]
        default_line = self._maybe_cyan(f"{indent}default: {ohi.default}")
        if not ohi.value_history:
            # Should never happen, but this keeps mypy happy.
            raise ValueError("No value history - options not parsed.")
        final_val = ohi.value_history.final_value
        curr_value_line = self._maybe_cyan(
            f"{indent}current value: {ohi.value_history.final_value.value}{maybe_parens(final_val.details)}"
        )

        interesting_ranked_values = [
            rv
            for rv in reversed(ohi.value_history.ranked_values)
            if rv.rank not in (Rank.NONE, Rank.HARDCODED, final_val.rank)
        ]
        value_derivation_lines = [
            self._maybe_cyan(f"{indent}     overrode: {rv.value}{maybe_parens(rv.details)}")
            for rv in interesting_ranked_values
        ]
        description_lines = [f"{indent}{s}" for s in wrap(ohi.help, 80)]
        lines = [
            *arg_lines,
            *choices_lines,
            default_line,
            curr_value_line,
            *value_derivation_lines,
            *description_lines,
        ]
        if ohi.deprecated_message:
            lines.append(self._maybe_red(f"{indent}{ohi.deprecated_message}."))
            if ohi.removal_hint:
                lines.append(self._maybe_red(f"{indent}{ohi.removal_hint}"))
        return lines
