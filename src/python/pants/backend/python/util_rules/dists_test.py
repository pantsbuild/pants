# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.util_rules import dists, pex
from pants.backend.python.util_rules.dists import (
    BuildSystem,
    DistBuildRequest,
    DistBuildResult,
    distutils_repr,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest
from pants.testutil.python_interpreter_selection import (
    skip_unless_python27_present,
    skip_unless_python39_present,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    ret = RuleRunner(
        rules=[
            *dists.rules(),
            *pex.rules(),
            QueryRule(DistBuildResult, [DistBuildRequest]),
        ],
    )
    ret.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return ret


def do_test_backend_shim(rule_runner: RuleRunner, constraints: str) -> None:
    setup_py = "from setuptools import setup; setup(name='foobar', version='1.2.3')"
    input_digest = rule_runner.request(
        Digest, [CreateDigest([FileContent("setup.py", setup_py.encode())])]
    )
    req = DistBuildRequest(
        build_system=BuildSystem(
            PexRequirements(
                # NB: These are the last versions compatible with Python 2.7.
                ["setuptools==44.1.1", "wheel==0.37.1"]
            ),
            "setuptools.build_meta",
        ),
        interpreter_constraints=InterpreterConstraints([constraints]),
        build_wheel=True,
        build_sdist=True,
        input=input_digest,
        working_directory="",
        dist_source_root=".",
        build_time_source_roots=tuple(),
        output_path="dist",
        wheel_config_settings=FrozenDict({"setting1": ("value1",), "setting2": ("value2",)}),
    )
    res = rule_runner.request(DistBuildResult, [req])

    is_py2 = "2.7" in constraints
    assert res.sdist_path == "dist/foobar-1.2.3.tar.gz"
    assert res.wheel_path == f"dist/foobar-1.2.3-py{'2' if is_py2 else '3'}-none-any.whl"


@skip_unless_python27_present
def test_works_with_python2(rule_runner: RuleRunner) -> None:
    do_test_backend_shim(rule_runner, constraints="CPython==2.7.*")


@skip_unless_python39_present
def test_works_with_python39(rule_runner: RuleRunner) -> None:
    do_test_backend_shim(rule_runner, constraints="CPython==3.9.*")


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
