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
from pants.backend.python.target_types import PythonDistribution, PythonSourcesGeneratorTarget
from pants.backend.python.util_rules import local_dists_pep660, pex_from_targets
from pants.backend.python.util_rules.dists import BuildSystem, DistBuildRequest
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists_pep660 import (
    LocalDistsPEP660Pex,
    LocalDistsPEP660PexRequest,
    PEP660BuildResult,
)
from pants.backend.python.util_rules.pex_from_targets import InterpreterConstraintsRequest
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.backend.python.util_rules.python_sources import PythonSourceFiles
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFiles
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent, Snapshot
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
            *local_dists_pep660.rules(),
            *setup_py_rules(),
            *setuptools_rules(),
            *target_types_rules.rules(),
            *pex_from_targets.rules(),
            QueryRule(InterpreterConstraints, (InterpreterConstraintsRequest,)),
            QueryRule(LocalDistsPEP660Pex, (LocalDistsPEP660PexRequest,)),
            QueryRule(PEP660BuildResult, (DistBuildRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonDistribution],
        objects={"python_artifact": PythonArtifact},
    )
    ret.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return ret


def do_test_backend_wrapper(rule_runner: RuleRunner, constraints: str) -> None:
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
        build_time_source_roots=tuple(),
        output_path="dist",
        wheel_config_settings=FrozenDict({"setting1": ("value1",), "setting2": ("value2",)}),
    )
    res = rule_runner.request(PEP660BuildResult, [req])

    is_py2 = "2.7" in constraints
    assert (
        res.editable_wheel_path
        == f"dist/foobar-1.2.3-0.editable-{'py2.' if is_py2 else ''}py3-none-any.whl"
    )


@skip_unless_python27_present
def test_works_with_python2(rule_runner: RuleRunner) -> None:
    do_test_backend_wrapper(rule_runner, constraints="CPython==2.7.*")


@skip_unless_python39_present
def test_works_with_python39(rule_runner: RuleRunner) -> None:
    do_test_backend_wrapper(rule_runner, constraints="CPython==3.9.*")


def test_build_editable_local_dists(rule_runner: RuleRunner) -> None:
    foo = PurePath("foo")
    rule_runner.write_files(
        {
            foo
            / "BUILD": dedent(
                """
            python_sources()

            python_distribution(
                name="dist",
                dependencies=[":foo"],
                provides=python_artifact(name="foo", version="9.8.7"),
                sdist=False,
                generate_setup=False,
            )
            """
            ),
            foo / "bar.py": "BAR = 42",
            foo
            / "setup.py": dedent(
                """
                from setuptools import setup

                setup(
                    name="foo",
                    version="9.8.7",
                    packages=["foo"],
                    package_dir={"foo": "."},
                    entry_points={"foo.plugins": ["bar = foo.bar.BAR"]},
                )
                """
            ),
        }
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    sources_digest = rule_runner.request(
        Digest,
        [
            CreateDigest(
                [FileContent("srcroot/foo/bar.py", b""), FileContent("srcroot/foo/qux.py", b"")]
            )
        ],
    )
    sources_snapshot = rule_runner.request(Snapshot, [sources_digest])
    sources = PythonSourceFiles(SourceFiles(sources_snapshot, tuple()), ("srcroot",))
    addresses = [Address("foo", target_name="dist")]
    interpreter_constraints = rule_runner.request(
        InterpreterConstraints, [InterpreterConstraintsRequest(addresses)]
    )
    request = LocalDistsPEP660PexRequest(
        addresses,
        sources=sources,
        interpreter_constraints=interpreter_constraints,
    )
    result = rule_runner.request(LocalDistsPEP660Pex, [request])

    assert result.pex is not None
    contents = rule_runner.request(DigestContents, [result.pex.digest])
    whl_content = None
    for content in contents:
        if content.path == "editable_local_dists.pex/.deps/foo-9.8.7-0.editable-py3-none-any.whl":
            whl_content = content
    assert whl_content
    with io.BytesIO(whl_content.content) as fp:
        with zipfile.ZipFile(fp, "r") as whl:
            whl_files = whl.namelist()
            # Check that sources are not present in editable wheel
            assert "foo/bar.py" not in whl_files
            assert "foo/qux.py" not in whl_files
            # Once installed, wheel does not have RECORD
            assert "foo-9.8.7.dist-info/RECORD" not in whl_files
            # Check that pth and metadata files are present in editable wheel
            assert "foo__pants__.pth" in whl_files
            assert "foo-9.8.7.dist-info/METADATA" in whl_files
            assert "foo-9.8.7.dist-info/WHEEL" in whl_files
            assert "foo-9.8.7.dist-info/direct_url__pants__.json" in whl_files
            assert "foo-9.8.7.dist-info/entry_points.txt" in whl_files

    # Check that all sources are not in the editable wheel
    assert result.remaining_sources.source_files.files == (
        "srcroot/foo/bar.py",
        "srcroot/foo/qux.py",
    )
