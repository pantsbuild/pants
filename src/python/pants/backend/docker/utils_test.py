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
        pytest.param(
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
            id="Copy'ing a folder, includes the entire tree below it",
        ),
        pytest.param(
            (
                "src.proj/bin_a.pex",
                "src.proj/binb.pex",
            ),
            ("src.proj/bin_a.pex",),
            ("src.proj",),
            [
                ("src.proj/binb.pex", ""),
            ],
            id="Should not suggest renaming to a file we already reference",
        ),
        pytest.param(
            (
                "src.proj/binb.pex",
                "src.proj/bin_a.pex",
            ),
            ("src.proj/bin_a.pex",),
            ("src.proj",),
            [
                ("src.proj/binb.pex", ""),
            ],
            id="Should not suggest renaming to a file we already reference, order should not matter",
        ),
        pytest.param(
            # I'm not entirely sure if `fnmatch` treats the ../*.pex the same as golangs
            # filepath.Match does. See notice comment in
            # pants.backend.docker.utils.suggest_renames().get_matches()
            (
                "src.proj/*.pex",
                "src.proj/config.ini",
            ),
            (
                "src.proj/bin_a.pex",
                "src.proj/bin_b.pex",
                "src.proj/other.txt",
                "src.proj/nested/file.txt",
                "src/proj/config.ini",
            ),
            (
                "src.proj",
                "src/proj",
                "src.proj/nested",
            ),
            [
                ("src.proj/config.ini", "src/proj/config.ini"),
                ("", "src.proj/nested/file.txt"),
                ("", "src.proj/other.txt"),
            ],
            id="Glob pattern captures matching files only",
        ),
        pytest.param(
            (
                "src/project/file",
                "sources",
            ),
            ("src/project/file",),
            (
                "src",
                "src/project",
            ),
            [
                ("sources", ""),
            ],
            id="Do not suggest renaming to an 'empty' directory",
        ),
        pytest.param(
            (
                "testprojects/src/python/docker/Dockerfile.test-example-synth",
                "testprojects.src.python.hello.main/mains.pez",
                "blarg",
                "baz",
            ),
            (
                "testprojects/src/python/docker/Dockerfile.test-example-synth",
                "testprojects.src.python.hello.main/main.pex",
            ),
            (
                "testprojects",
                "testprojects/src",
                "testprojects/src/python",
                "testprojects/src/python/docker",
                "testprojects.src.python.hello.main",
            ),
            [
                ("baz", ""),
                ("blarg", ""),
                (
                    "testprojects.src.python.hello.main/mains.pez",
                    "testprojects.src.python.hello.main/main.pex",
                ),
            ],
            id="Skip Dockerfile",
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
    "src, dst",
    [
        (
            "src/project/cmd.pex",
            "src.project/cmd.pex",
        ),
        (
            "srcs/projcet/cmd",
            "src/project/cmd.pex",
        ),
        (
            "src/bar-foo/file",
            "src/foo-bar/file",
        ),
    ],
)
def test_format_rename_suggestion(src: str, dst: str) -> None:
    actual = format_rename_suggestion(src, dst, colors=False)
    assert actual == f"{src} => {dst}"
