# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import io
import zipfile
from pathlib import PurePath
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals.setup_py import rules as setup_py_rules
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.setuptools import rules as setuptools_rules
from pants.backend.python.target_types import PythonDistribution, PythonLibrary
from pants.backend.python.util_rules import local_dists
from pants.backend.python.util_rules.local_dists import LocalDistsPex, LocalDistsPexRequest
from pants.build_graph.address import Address
from pants.engine.fs import DigestContents
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *local_dists.rules(),
            *setup_py_rules(),
            *setuptools_rules(),
            *target_types_rules.rules(),
            QueryRule(LocalDistsPex, (LocalDistsPexRequest,)),
        ],
        target_types=[PythonLibrary, PythonDistribution],
        objects={"python_artifact": PythonArtifact},
    )


def test_build_local_dists(rule_runner: RuleRunner) -> None:
    foo = PurePath("foo")
    rule_runner.write_files(
        {
            foo
            / "BUILD": dedent(
                """
            python_library()

            python_distribution(
                name = "dist",
                dependencies = [":foo"],
                provides = python_artifact(name="foo", version="9.8.7", setup_script="setup.py"),
                setup_py_commands = ["bdist_wheel",]
            )
            """
            ),
            foo / "bar.py": "BAR = 42",
            foo
            / "setup.py": dedent(
                """
                from setuptools import setup

                setup(name="foo", version="9.8.7", packages=["foo"], package_dir={"foo": "."},)
                """
            ),
        }
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    request = LocalDistsPexRequest([Address("foo", target_name="dist")])
    result = rule_runner.request(LocalDistsPex, [request])

    assert result.pex is not None
    contents = rule_runner.request(DigestContents, [result.pex.digest])
    assert len(contents) == 1
    with io.BytesIO(contents[0].content) as fp:
        with zipfile.ZipFile(fp, "r") as pex:
            assert ".deps/foo-9.8.7-py3-none-any.whl/foo/bar.py" in pex.namelist()
