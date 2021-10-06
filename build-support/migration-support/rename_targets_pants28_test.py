# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from rename_targets_pants28 import maybe_rewrite_build

from pants.util.contextutil import temporary_dir


def maybe_rewrite(content: str) -> str | None:
    with temporary_dir() as tmpdir:
        build = Path(tmpdir, "BUILD")
        build.write_text(content)
        return maybe_rewrite_build(build)


@pytest.mark.parametrize(
    "line",
    [
        "python_requirement()",
        "python_requirement ( )",
        "python_requirement(foo)",
        "python_requirement(\n)",
    ],
)
def test_no_op_when_already_valid(line: str) -> None:
    assert maybe_rewrite(line) is None


@pytest.mark.parametrize(
    "input,out",
    [
        ("python_requirement_library()", "python_requirement()"),
    ],
)
def test_rewrites(input: str, out: str) -> None:
    assert maybe_rewrite(input) == [out]


@pytest.mark.parametrize(
    "line", ["\n", "    123  ", "target()", "name='python_requirement_library'"]
)
def test_safe_with_unrelated_lines(line: str) -> None:
    assert maybe_rewrite(line) is None


def test_respects_original_formatting() -> None:
    assert maybe_rewrite("python_requirement_library ()") == ["python_requirement ()"]
    assert maybe_rewrite("python_requirement_library() ") == ["python_requirement() "]


def test_can_handle_comments() -> None:
    assert maybe_rewrite("python_requirement_library()  # test") == ["python_requirement()  # test"]


def test_can_handle_multiline() -> None:
    assert maybe_rewrite("python_requirement_library(\n)") == ["python_requirement(", ")"]


def test_ignores_indented() -> None:
    # Target definitions should be top-level function calls.
    assert maybe_rewrite("  python_requirement_library()") is None


def test_update_build_file() -> None:
    template = dedent(
        """\
        target(
            sources=['good.ext'],
        )

        {}()
        """
    )
    rewritten = maybe_rewrite(template.format("python_requirement_library"))
    assert "\n".join(rewritten or ()) + "\n" == template.format("python_requirement")
