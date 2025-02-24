# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


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
def test_complete_environment(input_strs: list[str], expected: dict[str, str]) -> None:
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


def test_envvar_fnmatch() -> None:
    """Test fnmatch patterns correctly pull in all matching envvars."""

    pants_env = CompleteEnvironmentVars(
        {
            "LETTER_C": "prefix_char_match",
            "LETTER_PI": "prefix",
            "LETTER_P*": "exact_match_with_glob",
            "letter_lower": "case-sensitive",
        }
    )

    char_match = pants_env.get_subset(["LETTER_?"])
    assert char_match == {"LETTER_C": "prefix_char_match"}

    multichar_match = pants_env.get_subset(["LETTER_*"])
    assert multichar_match == {
        "LETTER_C": "prefix_char_match",
        "LETTER_PI": "prefix",
        "LETTER_P*": "exact_match_with_glob",
    }

    exact_match_with_glob = pants_env.get_subset(["LETTER_P*"])
    assert exact_match_with_glob == {"LETTER_P*": "exact_match_with_glob"}

    case_sensitive = pants_env.get_subset(["LETTER_LOWER"])
    assert case_sensitive == {}
