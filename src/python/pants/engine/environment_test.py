# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, List

import pytest

from pants.engine.env_vars import CompleteEnvironmentVars


@pytest.mark.parametrize(
    "input_strs, expected",
    [
        # Test explicit variable and variable read from Pants' environment.
        (["A=unrelated", "B"], {"A": "unrelated", "B": "b"}),
        # Test multi-word string.
        (["A=unrelated", "C=multi word"], {"A": "unrelated", "C": "multi word"}),
        # Test empty string.
        (["A="], {"A": ""}),
        # Test string with " literal.
        (['A=has a " in it'], {"A": 'has a " in it'}),
    ],
)
def test_complete_environment(input_strs: List[str], expected: Dict[str, str]) -> None:
    pants_env = CompleteEnvironmentVars({"A": "a", "B": "b", "C": "c"})

    subset = pants_env.get_subset(input_strs)
    assert dict(subset) == expected


def test_invalid_variable() -> None:
    pants_env = CompleteEnvironmentVars()

    with pytest.raises(ValueError) as exc:
        pants_env.get_subset(["3INVALID=doesn't matter"])
    assert (
        "An invalid variable was requested via the --test-extra-env-var mechanism: 3INVALID"
        in str(exc)
    )
