# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.rules.setup_py_util import (
  declares_pkg_resources_namespace_package,
  distutils_repr,
)


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


def test_distutils_repr() -> None:
  assert expected == distutils_repr(testdata)


@pytest.mark.parametrize('python_src', [
  "__import__('pkg_resources').declare_namespace(__name__)",
  "\n__import__('pkg_resources').declare_namespace(__name__)  # type: ignore[attr-defined]",
  "import pkg_resources; pkg_resources.declare_namespace(__name__)",
  "from pkg_resources import declare_namespace; declare_namespace(__name__)",
])
def test_declares_pkg_resources_namespace_package(python_src: str) -> None:
  assert declares_pkg_resources_namespace_package(python_src)


@pytest.mark.parametrize('python_src', [
  "",
  "import os\n\nos.getcwd()",
  "__path__ = 'foo'",
  "import pkg_resources",
  "add(1, 2); foo(__name__); self.shoot(__name__)",
  "declare_namespace(bonk)",
  "just nonsense, not even parseable",
])
def test_does_not_declare_pkg_resources_namespace_package(python_src: str) -> None:
  assert not declares_pkg_resources_namespace_package(python_src)
