# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import pytest

from pants.engine.internals.target_adaptor import SourceBlock


@pytest.mark.parametrize(
    "inputs,expected",
    [
        [(SourceBlock(start=1, end=3), SourceBlock(start=2, end=4)), SourceBlock(start=2, end=3)],
        [(SourceBlock(start=1, end=4), SourceBlock(start=2, end=3)), SourceBlock(start=2, end=3)],
        [(SourceBlock(start=1, end=2), SourceBlock(start=3, end=4)), None],
    ],
)
def test_source_block_intersection(inputs: tuple[SourceBlock, SourceBlock], expected: SourceBlock):
    assert inputs[0].intersection(inputs[1]) == expected
    assert inputs[1].intersection(inputs[0]) == expected
