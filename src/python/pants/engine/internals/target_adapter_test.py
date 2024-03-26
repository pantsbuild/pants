# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from itertools import zip_longest

import pytest

from pants.engine.internals.target_adaptor import SourceBlock
from pants.vcs.hunk import TextBlock


@pytest.mark.parametrize(
    "inputs,expected",
    [
        # The TextBlock intersects with the SourceBlock.
        [(SourceBlock(start=4, end=6), TextBlock(start=5, count=2)), True],
        # The TextBlock is below and disjoint from the SourceBlock.
        [(SourceBlock(start=4, end=6), TextBlock(start=7, count=1)), False],
        # The TextBlock is above and disjoint from the SourceBlock.
        [(SourceBlock(start=4, end=6), TextBlock(start=2, count=1)), False],
        # The TextBlock touches or intersects with the SourceBlock.
        *[
            [(SourceBlock(start=4, end=6), TextBlock(start=start, count=1)), expected]
            for start, expected in zip_longest(
                range(2, 8),
                [False, True, True, True, True, False],
            )
        ],
        # The empty TextBlock touches or intersects with the SourceBlock.
        #
        # Keep in mind that TextBlock(start=2, count=0) means that something
        # was deleted between the lines 2 and 3.
        *[
            [(SourceBlock(start=4, end=6), TextBlock(start=start, count=0)), expected]
            for start, expected in zip_longest(
                range(2, 7),
                [False, True, True, True, False],
            )
        ],
        [(SourceBlock(start=1, end=7), TextBlock(start=15, count=0)), False],
    ],
)
def test_source_block_intersection(inputs: tuple[SourceBlock, TextBlock], expected: bool):
    assert inputs[0].is_touched_by(inputs[1]) == expected
