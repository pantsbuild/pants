# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from dataclasses import replace

from pants.help.help_formatter import HelpFormatter
from pants.help.help_info_extracter import HelpInfoExtracter, OptionHelpInfo


class OptionHelpFormatterTest(unittest.TestCase):
    @staticmethod
    def _format_for_single_option(**kwargs):
        ohi = OptionHelpInfo(
            display_args=("--foo",),
            comma_separated_display_args="--foo",
            scoped_cmd_line_args=("--foo",),
            unscoped_cmd_line_args=("--foo",),
            typ=bool,
            default=None,
            default_str="None",
            help="help for foo",
            deprecated_message=None,
            removal_version=None,
            removal_hint=None,
            choices=None,
        )
        ohi = replace(ohi, **kwargs)
        lines = HelpFormatter(
            show_advanced=False, show_deprecated=False, color=False
        ).format_option(ohi)
        assert len(lines) == 3
        assert "help for foo" in lines[2]
        return lines[1]

    def test_format_help(self):
        default_line = self._format_for_single_option(default="MYDEFAULT")
        assert default_line.lstrip() == "default: MYDEFAULT"

    def test_format_help_choices(self):
        default_line = self._format_for_single_option(
            typ=str, default="kiwi", choices="apple, banana, kiwi"
        )
        assert default_line.lstrip() == "one of: [apple, banana, kiwi]; default: kiwi"

    @staticmethod
    def _format_for_global_scope(show_advanced, show_deprecated, args, kwargs):
        oshi = HelpInfoExtracter("").get_option_scope_help_info("", [(args, kwargs)])
        return HelpFormatter(
            show_advanced=show_advanced, show_deprecated=show_deprecated, color=False
        ).format_options(oshi)

    def test_suppress_advanced(self):
        args = ["--foo"]
        kwargs = {"advanced": True}
        lines = self._format_for_global_scope(False, False, args, kwargs)
        assert len(lines) == 5
        assert not any("--foo" in line for line in lines)
        lines = self._format_for_global_scope(True, False, args, kwargs)
        assert len(lines) == 12

    def test_suppress_deprecated(self):
        args = ["--foo"]
        kwargs = {"removal_version": "33.44.55"}
        lines = self._format_for_global_scope(False, False, args, kwargs)
        assert len(lines) == 5
        assert not any("--foo" in line for line in lines)
        lines = self._format_for_global_scope(True, True, args, kwargs)
        assert len(lines) == 17
