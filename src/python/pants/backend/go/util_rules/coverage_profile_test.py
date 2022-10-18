# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

import pytest

from pants.backend.go.util_rules.coverage import GoCoverMode
from pants.backend.go.util_rules.coverage_profile import (
    GoCoverageProfile,
    GoCoverageProfileBlock,
    parse_go_coverage_profiles,
)

#
# This is a transcription of the Go coverage support library at
# https://cs.opensource.google/go/x/tools/+/master:cover/profile_test.go.
#
# Original copyright:
#   // Copyright 2019 The Go Authors. All rights reserved.
#   // Use of this source code is governed by a BSD-style
#   // license that can be found in the LICENSE file.
#


@dataclass(frozen=True)
class ProfileTestCase:
    name: str
    input: str
    profiles: tuple[GoCoverageProfile, ...] = ()
    expect_exception: bool = False


_TEST_CASES = [
    ProfileTestCase(
        name="parsing an empty file produces empty output",
        input="mode: set",
        profiles=(),
    ),
    ProfileTestCase(
        name="simple valid file produces expected output",
        input=dedent(
            """\
            mode: set
            some/fancy/path:42.69,44.16 2 1
            """
        ),
        profiles=(
            GoCoverageProfile(
                filename="some/fancy/path",
                cover_mode=GoCoverMode.SET,
                blocks=(
                    GoCoverageProfileBlock(
                        start_line=42,
                        start_col=69,
                        end_line=44,
                        end_col=16,
                        num_stmt=2,
                        count=1,
                    ),
                ),
            ),
        ),
    ),
    ProfileTestCase(
        name="file with syntax characters in path produces expected output",
        input=dedent(
            """\
            mode: set
            some fancy:path/some,file.go:42.69,44.16 2 1
            """
        ),
        profiles=(
            GoCoverageProfile(
                filename="some fancy:path/some,file.go",
                cover_mode=GoCoverMode.SET,
                blocks=(
                    GoCoverageProfileBlock(
                        start_line=42,
                        start_col=69,
                        end_line=44,
                        end_col=16,
                        num_stmt=2,
                        count=1,
                    ),
                ),
            ),
        ),
    ),
    ProfileTestCase(
        name="file with multiple blocks in one file produces expected output",
        input=dedent(
            """\
            mode: set
            some/fancy/path:42.69,44.16 2 1
            some/fancy/path:44.16,46.3 1 0
            """
        ),
        profiles=(
            GoCoverageProfile(
                filename="some/fancy/path",
                cover_mode=GoCoverMode.SET,
                blocks=(
                    GoCoverageProfileBlock(
                        start_line=42,
                        start_col=69,
                        end_line=44,
                        end_col=16,
                        num_stmt=2,
                        count=1,
                    ),
                    GoCoverageProfileBlock(
                        start_line=44,
                        start_col=16,
                        end_line=46,
                        end_col=3,
                        num_stmt=1,
                        count=0,
                    ),
                ),
            ),
        ),
    ),
    ProfileTestCase(
        name="file with multiple files produces expected output",
        input=dedent(
            """\
            mode: set
            another/fancy/path:44.16,46.3 1 0
            some/fancy/path:42.69,44.16 2 1
            """
        ),
        profiles=(
            GoCoverageProfile(
                filename="another/fancy/path",
                cover_mode=GoCoverMode.SET,
                blocks=(
                    GoCoverageProfileBlock(
                        start_line=44,
                        start_col=16,
                        end_line=46,
                        end_col=3,
                        num_stmt=1,
                        count=0,
                    ),
                ),
            ),
            GoCoverageProfile(
                filename="some/fancy/path",
                cover_mode=GoCoverMode.SET,
                blocks=(
                    GoCoverageProfileBlock(
                        start_line=42,
                        start_col=69,
                        end_line=44,
                        end_col=16,
                        num_stmt=2,
                        count=1,
                    ),
                ),
            ),
        ),
    ),
    ProfileTestCase(
        name="intertwined files are merged correctly",
        input=dedent(
            """\
            mode: set
            some/fancy/path:42.69,44.16 2 1
            another/fancy/path:47.2,47.13 1 1
            some/fancy/path:44.16,46.3 1 0
            """
        ),
        profiles=(
            GoCoverageProfile(
                filename="another/fancy/path",
                cover_mode=GoCoverMode.SET,
                blocks=(
                    GoCoverageProfileBlock(
                        start_line=47,
                        start_col=2,
                        end_line=47,
                        end_col=13,
                        num_stmt=1,
                        count=1,
                    ),
                ),
            ),
            GoCoverageProfile(
                filename="some/fancy/path",
                cover_mode=GoCoverMode.SET,
                blocks=(
                    GoCoverageProfileBlock(
                        start_line=42,
                        start_col=69,
                        end_line=44,
                        end_col=16,
                        num_stmt=2,
                        count=1,
                    ),
                    GoCoverageProfileBlock(
                        start_line=44,
                        start_col=16,
                        end_line=46,
                        end_col=3,
                        num_stmt=1,
                        count=0,
                    ),
                ),
            ),
        ),
    ),
    ProfileTestCase(
        name="duplicate blocks are merged correctly",
        input=dedent(
            """\
            mode: count
            some/fancy/path:42.69,44.16 2 4
            some/fancy/path:42.69,44.16 2 3
            """
        ),
        profiles=(
            GoCoverageProfile(
                filename="some/fancy/path",
                cover_mode=GoCoverMode.COUNT,
                blocks=(
                    GoCoverageProfileBlock(
                        start_line=42,
                        start_col=69,
                        end_line=44,
                        end_col=16,
                        num_stmt=2,
                        count=7,
                    ),
                ),
            ),
        ),
    ),
    ProfileTestCase(
        name="an invalid mode line is an error",
        input="mode:count",
        expect_exception=True,
    ),
    ProfileTestCase(
        name="a missing field is an error",
        input=dedent(
            """\
            mode: count
            some/fancy/path:42.69,44.16 2
            """
        ),
        expect_exception=True,
    ),
    ProfileTestCase(
        name="a missing path field is an error",
        input=dedent(
            """\
            mode: count
            42.69,44.16 2 3
            """
        ),
        expect_exception=True,
    ),
    ProfileTestCase(
        name="a non-numeric count is an error",
        input=dedent(
            """\
            mode: count
            42.69,44.16 2 nope
            """
        ),
        expect_exception=True,
    ),
    ProfileTestCase(
        name="an empty path is an error",
        input=dedent(
            """\
            mode: count
            :42.69,44.16 2 3
            """
        ),
        expect_exception=True,
    ),
    ProfileTestCase(
        name="a negative count is an error",
        input=dedent(
            """\
            mode: count
            some/fancy/path:42.69,44.16 2 -1
            """
        ),
        expect_exception=True,
    ),
]


@pytest.mark.parametrize("case", _TEST_CASES, ids=lambda c: c.name)  # type: ignore[no-any-return]
def test_parse_go_coverage_profiles(case) -> None:
    try:
        profiles = parse_go_coverage_profiles(case.input.encode(), description_of_origin="test")
        if case.expect_exception:
            raise ValueError(f"Expected exception but did not see it for test case `{case.name}`")
        assert profiles == case.profiles
    except Exception:
        if not case.expect_exception:
            raise
