# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from dataclasses import replace

from pants.help.help_formatter import HelpFormatter
from pants.help.help_info_extracter import OptionHelpInfo


class OptionHelpFormatterTest(unittest.TestCase):
    def format_help_for_foo(self, **kwargs):
        ohi = OptionHelpInfo(
            registering_class=type(None),
            display_args=["--foo"],
            comma_separated_display_args="--foo",
            scoped_cmd_line_args=["--foo"],
            unscoped_cmd_line_args=["--foo"],
            typ=bool,
            default=None,
            help="help for foo",
            deprecated_message=None,
            removal_version=None,
            removal_hint=None,
            choices=None,
        )
        ohi = replace(ohi, **kwargs)
        lines = HelpFormatter(
            scope="", show_advanced=False, show_deprecated=False, color=False
        ).format_option(ohi)
        assert len(lines) == 3
        assert "help for foo" in lines[2]
        return lines[1]

    def test_format_help(self):
        default_line = self.format_help_for_foo(default="MYDEFAULT")
        assert default_line.lstrip() == "default: MYDEFAULT"

    def test_format_help_choices(self):
        default_line = self.format_help_for_foo(
            typ=str, default="kiwi", choices="apple, banana, kiwi"
        )
        assert default_line.lstrip() == "one of: [apple, banana, kiwi]; default: kiwi"

    def test_suppress_advanced(self):
        args = ["--foo"]
        kwargs = {"advanced": True}
        lines = HelpFormatter(
            scope="", show_advanced=False, show_deprecated=False, color=False
        ).format_options(scope="", description="", option_registrations_iter=[(args, kwargs)])
        assert len(lines) == 5
        assert not any("--foo" in line for line in lines)
        lines = HelpFormatter(
            scope="", show_advanced=True, show_deprecated=False, color=False
        ).format_options(scope="", description="", option_registrations_iter=[(args, kwargs)])
        assert len(lines) == 12

    def test_suppress_deprecated(self):
        args = ["--foo"]
        kwargs = {"removal_version": "33.44.55"}
        lines = HelpFormatter(
            scope="", show_advanced=False, show_deprecated=False, color=False
        ).format_options(scope="", description="", option_registrations_iter=[(args, kwargs)])
        assert len(lines) == 5
        assert not any("--foo" in line for line in lines)
        lines = HelpFormatter(
            scope="", show_advanced=True, show_deprecated=True, color=False
        ).format_options(scope="", description="", option_registrations_iter=[(args, kwargs)])
        assert len(lines) == 17
