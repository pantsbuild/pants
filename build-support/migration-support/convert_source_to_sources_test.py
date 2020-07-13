# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path
from textwrap import dedent

import pytest
from convert_source_to_sources import maybe_rewrite_build, maybe_rewrite_line

from pants.util.contextutil import temporary_dir


@pytest.mark.parametrize(
    "line",
    [
        "sources=['foo.py'],",
        "sources= ('foo.py', ),"
        "sources = {'foo.py'},"
        "sources =['*.py'],"
        'sources =["!ignore.java"],',
        'sources   =    (    "!ignore.java",   )',
        '     sources=[""]',
    ],
)
def test_no_op_when_already_valid(line: str) -> None:
    assert maybe_rewrite_line(line) is None


@pytest.mark.parametrize(
    "line", ["\n", "    123  ", "python_library()", "name='hello'", "name='sources'",],
)
def test_safe_with_unrelated_lines(line: str) -> None:
    assert maybe_rewrite_line(line) is None


def test_respects_original_formatting() -> None:
    # Preserve whitespace around the `=` operator
    assert maybe_rewrite_line("source ='foo.py'") == "sources =['foo.py']"
    assert maybe_rewrite_line("source= 'foo.py'") == "sources= ['foo.py']"
    assert maybe_rewrite_line("source =  'foo.py'") == "sources =  ['foo.py']"

    # Preserve trailing commas
    assert maybe_rewrite_line("source='foo.py'") == "sources=['foo.py']"
    assert maybe_rewrite_line("source='foo.py',") == "sources=['foo.py'],"

    # Preserve leading whitespace
    assert maybe_rewrite_line("\t\tsource='foo.py'") == "\t\tsources=['foo.py']"
    assert maybe_rewrite_line("  source='foo.py'") == "  sources=['foo.py']"

    # Preserve trailing whitespace
    assert maybe_rewrite_line("source='foo.py'  ") == "sources=['foo.py']  "
    assert maybe_rewrite_line("source='foo.py',  ") == "sources=['foo.py'],  "

    # Preserve whether the original used single quotes or double quotes
    assert maybe_rewrite_line("source='foo.py'") == "sources=['foo.py']"
    assert maybe_rewrite_line('source="foo.py"') == 'sources=["foo.py"]'


def test_can_handle_sharing_a_line() -> None:
    assert (
        maybe_rewrite_line("python_library(source='foo.py')")
        == "python_library(sources=['foo.py'])"
    )
    assert maybe_rewrite_line("name='lib', source='foo.py'") == "name='lib', sources=['foo.py']"


def test_can_handle_comments() -> None:
    assert maybe_rewrite_line("source='foo.py'  # test") == "sources=['foo.py']  # test"
    assert maybe_rewrite_line("source = 'foo.py' ####") == "sources = ['foo.py'] ####"


def test_can_handle_variables() -> None:
    assert maybe_rewrite_line("source=VAR") == "sources=[VAR]"
    assert maybe_rewrite_line("source = x_y_z") == "sources = [x_y_z]"


def test_update_build_file() -> None:
    template = dedent(
        """\
        python_library(
            sources=['good.py'],
        )

        python_tests(
           {}
        )
        """
    )
    with temporary_dir() as tmpdir:
        build = Path(tmpdir, "BUILD")
        build.write_text(template.format("source='bad.py'"))
        rewritten = maybe_rewrite_build(build)
    assert "\n".join(rewritten) + "\n" == template.format("sources=['bad.py']")
