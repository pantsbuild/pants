# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.setup_py_util import distutils_repr


testdata = {
  'foo': 'bar',
  'baz': {
    'qux': [123, 456],
    'quux': ('abc', b'xyz'),
    'corge': {1, 2, 3}
  },
  'various_strings': [
    "x'y",
    'aaa\nbbb'
  ]
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


def test_distutils_repr():
  assert expected == distutils_repr(testdata)
