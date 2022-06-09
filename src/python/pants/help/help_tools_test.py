# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.help.help_info_extracter import HelpInfoExtracter
from pants.help.help_tools import ToolHelpInfo
from pants.help.maybe_color import MaybeColor
from pants.option.config import Config
from pants.option.global_options import GlobalOptions
from pants.option.parser import Parser


@pytest.fixture
def parser() -> Parser:
    return Parser(
        env={},
        config=Config.load([]),
        scope_info=GlobalOptions.get_scope_info(),
    )


@pytest.fixture
def extracter() -> HelpInfoExtracter:
    return HelpInfoExtracter("test")


@pytest.fixture
def tool_info(extracter, parser) -> ToolHelpInfo:
    parser.register("version", typ=str, default="1.0")
    parser.register("url-template", typ=str, default="https://download/{version}")
    oshi = extracter.get_option_scope_help_info("Test description.", parser, False)
    tool_info = ToolHelpInfo.from_option_scope_help_info(oshi)
    assert tool_info is not None
    return tool_info


def test_no_tool_help_info(extracter, parser) -> None:
    oshi = extracter.get_option_scope_help_info("", parser, False)
    assert ToolHelpInfo.from_option_scope_help_info(oshi) is None


def test_tool_help_info(tool_info) -> None:
    assert tool_info.name == "test"
    assert tool_info.version == "1.0"
    assert tool_info.description == "Test description."
    assert tool_info.url_template == "https://download/{version}"


def test_print_tool_help_info(capsys, tool_info) -> None:
    tool_info.print(MaybeColor(False), 6, 80)
    captured = capsys.readouterr()
    assert captured.out == dedent(
        """\
        test  Test description.
              Version: 1.0
              URL template: https://download/{version}

        """
    )
