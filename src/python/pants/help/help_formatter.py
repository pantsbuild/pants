# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import wrap
from typing import List

from colors import cyan, green, magenta, red

from pants.help.help_info_extracter import HelpInfoExtracter, OptionHelpInfo


class HelpFormatter:
    def __init__(
        self, *, scope: str, show_advanced: bool, show_deprecated: bool, color: bool
    ) -> None:
        self._scope = scope
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

    def format_options(self, scope, description, option_registrations_iter):
        """Return a help message for the specified options.

        :param scope: The options scope.
        :param description: The description of the scope.
        :param option_registrations_iter: An iterator over (args, kwargs) pairs, as passed in to
                                          options registration.
        """
        oshi = HelpInfoExtracter(self._scope).get_option_scope_help_info(option_registrations_iter)
        lines = []

        def add_option(ohis, *, category=None):
            lines.append("")
            display_scope = f"`{scope}`" if scope else "Global"
            if category:
                title = f"{display_scope} {category} options"
                lines.append(self._maybe_green(f"{title}\n{'-' * len(title)}"))
            else:
                title = f"{display_scope} options"
                lines.append(self._maybe_green(f"{title}\n{'-' * len(title)}"))
                if description:
                    lines.append(f"\n{description}")
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
        indent = "      "
        arg_line = f"  {self._maybe_magenta(', '.join(ohi.display_args))}"
        choices = f"one of: [{ohi.choices}]; " if ohi.choices else ""
        default_lines = [
            f"{indent}{'  ' if i != 0 else ''}{self._maybe_cyan(s)}"
            for i, s in enumerate(wrap(f"{choices}default: {ohi.default}", 80))
        ]
        description_lines = [f"{indent}{s}" for s in wrap(ohi.help, 80)]
        lines = [arg_line, *default_lines, *description_lines]
        if ohi.deprecated_message:
            lines.append(self._maybe_red(f"{indent}{ohi.deprecated_message}."))
            if ohi.removal_hint:
                lines.append(self._maybe_red(f"{indent}{ohi.removal_hint}"))
        return lines
