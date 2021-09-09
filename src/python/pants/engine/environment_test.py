# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, List

import pytest

from pants.engine.environment import (
    CompleteEnvironment,
    InterpolatedEnvironmentRequest,
    interpolated_subset,
)


@pytest.mark.parametrize(
    "input_strs, expected",
    [
        # Test explicit variable and variable read from Pants' enivronment.
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
    pants_env = CompleteEnvironment({"A": "a", "B": "b", "C": "c"})

    subset = pants_env.get_subset(input_strs)
    assert dict(subset) == expected


def test_invalid_variable() -> None:
    pants_env = CompleteEnvironment()

    with pytest.raises(ValueError) as exc:
        pants_env.get_subset(["3INVALID=doesn't matter"])
    assert (
        "An invalid variable was requested via the --test-extra-env-var mechanism: 3INVALID"
        in str(exc)
    )


@pytest.mark.parametrize(
    "input_dict, environment, expected",
    [
        ({"foo": "FOO"}, {}, {"foo": "FOO"}),
        ({"foo": "$FOO"}, {}, {"foo": "$FOO"}),
        ({"foo": "${FOO}"}, {}, {}),
        ({"foo": "${FOO}"}, {"FOO": "bar"}, {"foo": "bar"}),
        ({"foo": "${FOO}", "bar": "BAR"}, {"FOO": "bar"}, {"foo": "bar", "bar": "BAR"}),
    ],
)
def test_interpolated_subset(input_dict, environment, expected):
    session_values = {CompleteEnvironment: environment}
    request = InterpolatedEnvironmentRequest(input_dict)

    subset = interpolated_subset(session_values, request)

    assert dict(subset) == expected
