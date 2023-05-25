# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re

import pytest

from pants.backend.python.macros.python_artifact import _normalize_entry_points
from pants.testutil.pytest_util import no_exception


@pytest.mark.parametrize(
    "entry_points, normalized, expect",
    [
        (
            dict(console_scripts=dict(foo="bar:baz")),
            dict(console_scripts=dict(foo="bar:baz")),
            no_exception(),
        ),
        (
            dict(console_scripts=["foo=bar:baz", "barty=slouch:ing"]),
            dict(console_scripts=dict(foo="bar:baz", barty="slouch:ing")),
            no_exception(),
        ),
        (
            dict(
                console_scripts=["foo=bar:baz"],
                other_plugins=["plug=this.ok"],
                my=dict(already="norm.alize:d"),
            ),
            dict(
                console_scripts=dict(foo="bar:baz"),
                other_plugins=dict(plug="this.ok"),
                my=dict(already="norm.alize:d"),
            ),
            no_exception(),
        ),
        (
            ["not=ok"],
            None,
            pytest.raises(
                ValueError,
                match=re.escape(
                    r"The `entry_points` in `python_artifact()` must be a dictionary, but was ['not=ok'] with type list."
                ),
            ),
        ),
        (
            dict(ep=["missing.name:here"]),
            None,
            pytest.raises(
                ValueError,
                match=re.escape(
                    r"Invalid `entry_point`, expected `<name> = <entry point>`, but got 'missing.name:here'."
                ),
            ),
        ),
        (
            dict(ep="whops = this.is.a:mistake"),
            None,
            pytest.raises(
                ValueError,
                match=re.escape(
                    r"The values of the `entry_points` dictionary in `python_artifact()` must be a list of strings "
                    r"or a dictionary of string to string, but got 'whops = this.is.a:mistake' of type str."
                ),
            ),
        ),
    ],
)
def test_normalize_entry_points(entry_points, normalized, expect) -> None:
    with expect:
        assert _normalize_entry_points(entry_points) == normalized
