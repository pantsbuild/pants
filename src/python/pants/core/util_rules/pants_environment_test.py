# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, List

import pytest

from pants.core.util_rules.pants_environment import PantsEnvironment


@pytest.mark.parametrize(
    "input_strs, expected",
    [
        # Test explicit variable and variable read from Pants' enivronment.
        (["A=unrelated", "B"], {"A": "unrelated", "B": "b"}),
        # Test multi-word string.
        (["A=unrelated", "C=multi word"], {"A": "unrelated", "C": "multi word"}),
        # Test emtpy string.
        (["A="], {"A": ""}),
        # Test string with " literal.
        (['A=has a " in it'], {"A": 'has a " in it'}),
        # An invalid variable name should be skipped.
        (["3INVALID=doesn't matter"], {}),
    ],
)
def test_pants_environment(input_strs: List[str], expected: Dict[str, str]) -> None:
    pants_env = PantsEnvironment({"A": "a", "B": "b", "C": "c"})

    subset = pants_env.get_subset(input_strs)
    assert dict(subset) == expected
