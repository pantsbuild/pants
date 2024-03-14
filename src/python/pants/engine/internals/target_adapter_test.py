import pytest

from pants.engine.internals.target_adaptor import TextBlock


@pytest.mark.parametrize(
    "inputs,expected",
    [
        [(TextBlock(start=1, end=3), TextBlock(start=2, end=4)), TextBlock(start=2, end=3)],
        [(TextBlock(start=1, end=4), TextBlock(start=2, end=3)), TextBlock(start=2, end=3)],
        [(TextBlock(start=1, end=2), TextBlock(start=3, end=4)), None],
    ],
)
def test_text_block_intersection(inputs: tuple[TextBlock, TextBlock], expected: TextBlock):
    assert inputs[0].intersection(inputs[1]) == expected
    assert inputs[1].intersection(inputs[0]) == expected
