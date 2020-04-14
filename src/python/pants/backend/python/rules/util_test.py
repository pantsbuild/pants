# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.python.rules.util import (
    declares_pkg_resources_namespace_package,
    distutils_repr,
    is_python2,
)
from pants.option.ranked_value import Rank, RankedValue
from pants.python.python_setup import PythonSetup
from pants.subsystem.subsystem import Subsystem
from pants.testutil.subsystem.util import init_subsystem

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


def test_distutils_repr() -> None:
    assert expected == distutils_repr(testdata)


@pytest.mark.parametrize(
    "python_src",
    [
        "__import__('pkg_resources').declare_namespace(__name__)",
        "\n__import__('pkg_resources').declare_namespace(__name__)  # type: ignore[attr-defined]",
        "import pkg_resources; pkg_resources.declare_namespace(__name__)",
        "from pkg_resources import declare_namespace; declare_namespace(__name__)",
    ],
)
def test_declares_pkg_resources_namespace_package(python_src: str) -> None:
    assert declares_pkg_resources_namespace_package(python_src)


@pytest.mark.parametrize(
    "python_src",
    [
        "",
        "import os\n\nos.getcwd()",
        "__path__ = 'foo'",
        "import pkg_resources",
        "add(1, 2); foo(__name__); self.shoot(__name__)",
        "declare_namespace(bonk)",
        "just nonsense, not even parseable",
    ],
)
def test_does_not_declare_pkg_resources_namespace_package(python_src: str) -> None:
    assert not declares_pkg_resources_namespace_package(python_src)


@pytest.mark.parametrize(
    ["constraints", "compatibilities"],
    [
        ([], [["CPython>=2.7,<3"]]),
        (["CPython>=2.7,<3"], [None]),
        (["CPython>=2.7,<3"], [["CPython>=2.7,<3"], ["CPython>=3.6"]]),
        (["CPython>=2.7.13"], [None]),
        (["CPython>=2.7.13,<2.7.16"], [None]),
        (["CPython>=2.7.13,!=2.7.16"], [None]),
        (["PyPy>=2.7,<3"], [None]),
    ],
)
def test_is_python2(constraints, compatibilities):
    Subsystem.reset()
    init_subsystem(
        PythonSetup,
        {
            PythonSetup.options_scope: {
                "interpreter_constraints": RankedValue(Rank.CONFIG, constraints)
            }
        },
    )
    assert is_python2(compatibilities, PythonSetup.global_instance())


@pytest.mark.parametrize(
    ["constraints", "compatibilities"],
    [
        ([], [["CPython>=3.6"]]),
        (["CPython>=3.6"], [None]),
        (["CPython>=3.7"], [["CPython>=3.6"]]),
        (["CPython>=3.7"], [["CPython>=3.6"], ["CPython>=3.8"]]),
        (["CPython!=2.7.*"], [None]),
        (["PyPy>=3.6"], [None]),
    ],
)
def test_is_not_python2(constraints, compatibilities):
    Subsystem.reset()
    init_subsystem(
        PythonSetup,
        {
            PythonSetup.options_scope: {
                "interpreter_constraints": RankedValue(Rank.CONFIG, constraints)
            }
        },
    )
    assert not is_python2(compatibilities, PythonSetup.global_instance())
