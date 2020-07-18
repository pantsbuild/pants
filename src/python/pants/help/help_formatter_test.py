# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from dataclasses import replace

from pants.help.help_formatter import HelpFormatter
from pants.help.help_info_extracter import HelpInfoExtracter, OptionHelpInfo
from pants.option.config import Config
from pants.option.global_options import GlobalOptions
from pants.option.option_value_container import OptionValueContainer
from pants.option.parser import OptionValueHistory, Parser
from pants.option.ranked_value import Rank, RankedValue


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
            comma_separated_choices=None,
            value_history=OptionValueHistory((RankedValue(Rank.HARDCODED, None),)),
        )
        ohi = replace(ohi, **kwargs)
        lines = HelpFormatter(
            show_advanced=False, show_deprecated=False, color=False
        ).format_option(ohi)
        choices = kwargs.get("choices")
        assert len(lines) == 5 if choices else 4
        if choices:
            assert f"one of: [{', '.join(choices)}]" == lines[1].strip()
        assert "help for foo" in lines[4 if choices else 3]
        return lines[2] if choices else lines[1]

    def test_format_help(self):
        default_line = self._format_for_single_option(default="MYDEFAULT")
        assert default_line.lstrip() == "default: MYDEFAULT"

    def test_format_help_choices(self):
        default_line = self._format_for_single_option(
            typ=str, default="kiwi", choices=["apple", "banana", "kiwi"]
        )
        assert default_line.lstrip() == "default: kiwi"

    @staticmethod
    def _format_for_global_scope(show_advanced, show_deprecated, args, kwargs):
        parser = Parser(
            env={},
            config=Config.load([]),
            scope_info=GlobalOptions.get_scope_info(),
            parent_parser=None,
        )
        parser.register(*args, **kwargs)
        # Force a parse to generate the derivation history.
        parser.parse_args(Parser.ParseArgsRequest((), OptionValueContainer(), lambda: [], 0, []))
        oshi = HelpInfoExtracter("").get_option_scope_help_info("", parser, False)
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
        assert len(lines) == 13

    def test_suppress_deprecated(self):
        args = ["--foo"]
        kwargs = {"removal_version": "33.44.55.dev0"}
        lines = self._format_for_global_scope(False, False, args, kwargs)
        assert len(lines) == 5
        assert not any("--foo" in line for line in lines)
        lines = self._format_for_global_scope(True, True, args, kwargs)
        assert len(lines) == 18
