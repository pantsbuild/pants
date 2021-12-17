# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.docker.utils import format_rename_suggestion, suggest_renames


@pytest.mark.parametrize(
    "tentative_paths, actual_files, actual_dirs, expected_renames",
    [
        (
            ("src/project/cmd.pex",),
            ("src.project/cmd.pex",),
            (),
            [("src/project/cmd.pex", "src.project/cmd.pex")],
        ),
        (
            ("src/project/cmd.pex",),
            ("src/unrelated/file.py",),
            ("src/unrelated",),
            [
                # "false" positive, this is not an expected "correct" rename suggestion, but it was
                # all we got here.
                ("src/project/cmd.pex", "src/unrelated/file.py"),
            ],
        ),
        (
            # Copy'ing a folder, includes the entire tree below it.
            ("files",),
            (
                "src/docker/files/a.txt",
                "src/docker/files/b.txt",
                "src/docker/files/sub/c.txt",
                "src/docker/config.ini",
            ),
            ("src", "src/docker", "src/docker/files"),
            [
                ("files", "src/docker/files"),
                ("", "src/docker/config.ini"),
            ],
        ),
    ],
)
def test_suggest_renames(
    tentative_paths: tuple[str, ...],
    actual_files: tuple[str, ...],
    actual_dirs: tuple[str, ...],
    expected_renames: list[tuple[str, str]],
) -> None:
    actual_renames = list(suggest_renames(tentative_paths, actual_files, actual_dirs))
    assert actual_renames == expected_renames


@pytest.mark.parametrize(
    "src, dst, expected",
    [
        (
            "src/project/cmd.pex",
            "src.project/cmd.pex",
            "src{/ => .}project/cmd.pex",
        ),
        (
            "srcs/projcet/cmd",
            "src/project/cmd.pex",
            "src{s => }/proj{ => e}c{e => }t/cmd{ => .pex}",
        ),
        (
            "src/bar-foo/file",
            "src/foo-bar/file",
            "src/{ => foo-}bar{-foo => }/file",
        ),
    ],
)
def test_format_rename_suggestion(src: str, dst: str, expected: str) -> None:
    actual = format_rename_suggestion(src, dst, colors=False)
    assert actual == expected
