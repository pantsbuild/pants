# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import math
import re
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.go.util_rules.coverage import GoCoverMode
from pants.util.strutil import strip_prefix

#
# This is a transcription of the Go coverage support library at
# https://cs.opensource.google/go/x/tools/+/master:cover/profile.go.
#
# Original copyright:
#   // Copyright 2013 The Go Authors. All rights reserved.
#   // Use of this source code is governed by a BSD-style
#   // license that can be found in the LICENSE file.
#


@dataclass(frozen=True)
class GoCoverageProfileBlock:
    start_line: int
    start_col: int
    end_line: int
    end_col: int
    num_stmt: int
    count: int


@dataclass(frozen=True)
class GoCoverageBoundary:
    offset: int
    start: bool
    count: int
    norm: float
    index: int


@dataclass(frozen=True)
class GoCoverageProfile:
    """Parsed representation of a raw Go coverage profile for a single file.

    A coverage output file may report on multiple files which will be split into different instances
    of this dataclass.
    """

    filename: str
    cover_mode: GoCoverMode
    blocks: tuple[GoCoverageProfileBlock, ...]

    def boundaries(self, src: bytes) -> tuple[GoCoverageBoundary, ...]:
        max_count = 0
        for block in self.blocks:
            if block.count > max_count:
                max_count = block.count
        # Note: Python throws ValueError if max_count == 0
        divisor = math.log(max_count) if max_count > 0 else 0

        index = 0

        def boundary(offset: int, start: bool, count: int) -> GoCoverageBoundary:
            nonlocal index, max_count
            b = GoCoverageBoundary(offset=offset, start=start, count=count, norm=0.0, index=index)
            index = index + 1
            if not start or count == 0:
                return b
            new_norm = None
            if max_count <= 1:
                new_norm = 0.8  # Profile is in "set" mode; we want a heat map. Use cov8 in the CSS.
            elif count > 0:
                # Divide by zero avoided since divisor > 0 if max_count > 1.
                # TODO: What if max_count == 1 so divisor == 0?
                new_norm = math.log(count) / divisor
            if new_norm is not None:
                b = dataclasses.replace(b, norm=new_norm)
            return b

        line, col = 1, 2  # TODO: Why is this 2?
        si, bi = 0, 0
        boundaries = []
        while si < len(src) and bi < len(self.blocks):
            b = self.blocks[bi]
            if b.start_line == line and b.start_col == col:
                boundaries.append(boundary(si, True, b.count))
            if b.end_line == line and b.end_col == col or line > b.end_line:
                boundaries.append(boundary(si, False, 0))
                bi += 1
                continue  # Don't advance through src; maybe the next block starts here.
            if src[si] == ord("\n"):
                line += 1
                col = 0
            col += 1
            si += 1

        boundaries.sort(key=lambda b: (b.offset, b.index))
        return tuple(boundaries)


_BLOCK_REGEX = re.compile(r"^(.+):([0-9]+)\.([0-9]+),([0-9]+)\.([0-9]+) ([0-9]+) ([0-9]+)$")


def parse_go_coverage_profiles(
    contents: bytes, *, description_of_origin: str
) -> tuple[GoCoverageProfile, ...]:
    lines = iter(contents.decode().splitlines())

    # Extract the mode line from the first line.
    mode_line = next(lines)
    if not mode_line.startswith("mode: "):
        raise ValueError(
            f"Malformed Go coverage file from {description_of_origin}: invalid cover mode specifier"
        )

    raw_mode = strip_prefix(mode_line, "mode: ")
    cover_mode = GoCoverMode(raw_mode)

    # Parse the coverage blocks from the remainder of the file.
    blocks_by_file: dict[str, list[GoCoverageProfileBlock]] = defaultdict(list)
    for line in lines:
        parsed_profile_line = _BLOCK_REGEX.fullmatch(line)
        if not parsed_profile_line:
            raise ValueError(
                f"Malformed Go coverage file from {description_of_origin}: invalid profile block line"
            )

        filename = parsed_profile_line.group(1)
        start_line = int(parsed_profile_line.group(2))
        start_col = int(parsed_profile_line.group(3))
        end_line = int(parsed_profile_line.group(4))
        end_col = int(parsed_profile_line.group(5))
        num_stmt = int(parsed_profile_line.group(6))
        count = int(parsed_profile_line.group(7))

        blocks_by_file[filename].append(
            GoCoverageProfileBlock(
                start_line=start_line,
                start_col=start_col,
                end_line=end_line,
                end_col=end_col,
                num_stmt=num_stmt,
                count=count,
            )
        )

    profiles = [
        GoCoverageProfile(
            filename=filename,
            cover_mode=cover_mode,
            blocks=tuple(blocks),
        )
        for filename, blocks in blocks_by_file.items()
    ]

    # Merge blocks from the same location.
    for profile_index, profile in enumerate(profiles):
        blocks = list(profile.blocks)
        blocks.sort(key=lambda b: (b.start_line, b.start_col))
        j = 1
        for i in range(1, len(blocks)):
            b = blocks[i]
            last = blocks[j - 1]
            if (
                b.start_line == last.start_line
                and b.start_col == last.start_col
                and b.end_line == last.end_line
                and b.end_col == last.end_col
            ):
                if b.num_stmt != last.num_stmt:
                    raise ValueError(
                        f"inconsistent NumStmt: changed from {last.num_stmt} to {b.num_stmt}"
                    )
                if cover_mode == GoCoverMode.SET:
                    blocks[j - 1] = dataclasses.replace(
                        blocks[j - 1], count=blocks[j - 1].count | b.count
                    )
                else:
                    blocks[j - 1] = dataclasses.replace(
                        blocks[j - 1], count=blocks[j - 1].count + b.count
                    )
                continue
            blocks[j] = b
            j = j + 1

        profiles[profile_index] = dataclasses.replace(profile, blocks=tuple(blocks[:j]))

    profiles.sort(key=lambda p: p.filename)
    return tuple(profiles)
