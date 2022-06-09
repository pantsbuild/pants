# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.util_rules.dists import distutils_repr


def test_distutils_repr() -> None:
    testdata = {
        "foo": "bar",
        "baz": {"qux": [123, 456], "quux": ("abc", b"xyz"), "corge": {1, 2, 3}},
        "various_strings": ["x'y", "aaa\nbbb"],
    }
    expected = """
{
    'foo': 'bar',
    'baz': {
        'qux': [
            123,
            456,
        ],
        'quux': (
            'abc',
            'xyz',
        ),
        'corge': {
            1,
            2,
            3,
        },
    },
    'various_strings': [
        'x\\\'y',
        \"\"\"aaa\nbbb\"\"\",
    ],
}
""".strip()
    assert expected == distutils_repr(testdata)


def test_distutils_repr_none() -> None:
    assert "None" == distutils_repr(None)
