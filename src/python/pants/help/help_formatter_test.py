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
      scope="", show_recursive=False, show_advanced=False, color=False
    ).format_option(ohi)
    assert len(lines) == 2
    assert "help for foo" in lines[1]
    return lines[0]

  def test_format_help(self):
    line = self.format_help_for_foo(default="MYDEFAULT")
    assert line.lstrip() == "--foo (default: MYDEFAULT)"

  def test_suppress_advanced(self):
    args = ["--foo"]
    kwargs = {"advanced": True}
    lines = HelpFormatter(
      scope="", show_recursive=False, show_advanced=False, color=False
    ).format_options(scope="", description="", option_registrations_iter=[(args, kwargs)])
    assert len(lines) == 5
    assert not any("--foo" in line for line in lines)
    lines = HelpFormatter(
      scope="", show_recursive=True, show_advanced=True, color=False
    ).format_options(scope="", description="", option_registrations_iter=[(args, kwargs)])
    assert len(lines) == 14

  def test_format_help_choices(self):
    line = self.format_help_for_foo(typ=str, default="kiwi", choices="apple, banana, kiwi")
    assert line.lstrip() == "--foo (one of: [apple, banana, kiwi] default: kiwi)"
