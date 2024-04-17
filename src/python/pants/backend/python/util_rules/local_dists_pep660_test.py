# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import io
import json
import zipfile
from pathlib import PurePath
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.subsystems.setuptools import rules as setuptools_rules
from pants.backend.python.target_types import PythonDistribution, PythonSourcesGeneratorTarget
from pants.backend.python.util_rules import local_dists_pep660, pex_from_targets
from pants.backend.python.util_rules.dists import BuildSystem, DistBuildRequest
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.local_dists_pep660 import (
    EditableLocalDists,
    EditableLocalDistsRequest,
    PEP660BuildResult,
    ResolveSortedPythonDistributionTargets,
)
from pants.backend.python.util_rules.pex_from_targets import InterpreterConstraintsRequest
from pants.backend.python.util_rules.pex_requirements import PexRequirements
from pants.build_graph.address import Address
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent
from pants.engine.internals.parametrize import Parametrize
from pants.testutil.python_interpreter_selection import (
    skip_unless_python27_present,
    skip_unless_python39_present,
)
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    ret = PythonRuleRunner(
        rules=[
            *local_dists_pep660.rules(),
            *setuptools_rules(),
            *target_types_rules.rules(),
            *pex_from_targets.rules(),
            QueryRule(InterpreterConstraints, (InterpreterConstraintsRequest,)),
            QueryRule(ResolveSortedPythonDistributionTargets, ()),
            QueryRule(EditableLocalDists, (EditableLocalDistsRequest,)),
            QueryRule(PEP660BuildResult, (DistBuildRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonDistribution],
        objects={"python_artifact": PythonArtifact, "parametrize": Parametrize},
    )
    ret.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return ret


def do_test_backend_wrapper(rule_runner: PythonRuleRunner, constraints: str) -> None:
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
    res = rule_runner.request(PEP660BuildResult, [req])

    is_py2 = "2.7" in constraints
    assert (
        res.editable_wheel_path
        == f"dist/foobar-1.2.3-0.editable-{'py2.' if is_py2 else ''}py3-none-any.whl"
    )


@skip_unless_python27_present
def test_works_with_python2(rule_runner: PythonRuleRunner) -> None:
    do_test_backend_wrapper(rule_runner, constraints="CPython==2.7.*")


@skip_unless_python39_present
def test_works_with_python39(rule_runner: PythonRuleRunner) -> None:
    do_test_backend_wrapper(rule_runner, constraints="CPython==3.9.*")


def test_sort_all_python_distributions_by_resolve(rule_runner: PythonRuleRunner) -> None:
    rule_runner.set_options(
        [
            "--python-enable-resolves=True",
            "--python-resolves={'a': 'lock.txt', 'b': 'lock.txt'}",
            # Turn off lockfile validation to make the test simpler.
            "--python-invalid-lockfile-behavior=ignore",
            # Turn off python synthetic lockfile targets to make the test simpler.
            "--no-python-enable-lockfile-targets",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    rule_runner.write_files(
        {
            "foo/BUILD": dedent(
                """
                python_sources(resolve=parametrize("a", "b"))

                python_distribution(
                    name="dist",
                    dependencies=[":foo@resolve=a"],
                    provides=python_artifact(name="foo", version="9.8.7"),
                    sdist=False,
                    generate_setup=False,
                )
                """
            ),
            "foo/bar.py": "BAR = 42",
            "foo/setup.py": dedent(
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
            "lock.txt": "",
        }
    )
    dist = rule_runner.get_target(Address("foo", target_name="dist"))
    result = rule_runner.request(ResolveSortedPythonDistributionTargets, ())
    assert len(result.targets) == 1
    assert "b" not in result.targets
    assert "a" in result.targets
    assert len(result.targets["a"]) == 1
    assert dist == result.targets["a"][0]


def test_build_editable_local_dists(rule_runner: PythonRuleRunner) -> None:
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
    request = EditableLocalDistsRequest(
        resolve=None,  # resolves is disabled
    )
    result = rule_runner.request(EditableLocalDists, [request])

    assert result.optional_digest is not None
    contents = rule_runner.request(DigestContents, [result.optional_digest])
    assert len(contents) == 1
    whl_content = contents[0]
    assert whl_content
    assert whl_content.path == "foo-9.8.7-0.editable-py3-none-any.whl"
    with io.BytesIO(whl_content.content) as fp:
        with zipfile.ZipFile(fp, "r") as whl:
            whl_files = whl.namelist()
            # Check that sources are not present in editable wheel
            assert "foo/bar.py" not in whl_files
            assert "foo/qux.py" not in whl_files
            # Check that pth and metadata files are present in editable wheel
            assert "foo__pants__.pth" in whl_files
            assert "foo-9.8.7.dist-info/METADATA" in whl_files
            assert "foo-9.8.7.dist-info/RECORD" in whl_files
            assert "foo-9.8.7.dist-info/WHEEL" in whl_files
            assert "foo-9.8.7.dist-info/direct_url__pants__.json" in whl_files
            assert "foo-9.8.7.dist-info/entry_points.txt" in whl_files


def test_build_editable_local_dists_special_files(rule_runner: PythonRuleRunner) -> None:
    # we need multiple source roots to make sure that any dependencies
    # from other source roots do not end up listed as the direct_url.
    pkgs = ("a", "b", "c")
    for pkg in pkgs:
        root = PurePath(f"root_{pkg}")
        rule_runner.write_files(
            {
                root / pkg / "BUILD": "python_sources()\n",
                root / pkg / "__init__.py": "",
                root / pkg / "bar.py": "BAR = 42" if pkg == "a" else "from a.bar import BAR",
                root
                / "BUILD": dedent(
                    f"""
                    python_sources()

                    python_distribution(
                        name="dist",
                        dependencies=["./{pkg}", ":root_{pkg}"],
                        provides=python_artifact(name="{pkg}", version="9.8.7"),
                        sdist=False,
                        generate_setup=False,
                    )
                    """
                ),
                root
                / "setup.py": dedent(
                    f"""
                    from setuptools import setup

                    setup(
                        name="{pkg}",
                        version="9.8.7",
                        packages=["{pkg}"],
                        entry_points={{"foo.plugins": ["{pkg} = {pkg}.bar.BAR"]}},
                    )
                    """
                ),
            }
        )

    args = [
        "--source-root-patterns=root_*",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})

    request = EditableLocalDistsRequest(
        resolve=None,  # resolves is disabled
    )
    result = rule_runner.request(EditableLocalDists, [request])

    assert result.optional_digest is not None
    contents = rule_runner.request(DigestContents, [result.optional_digest])
    assert len(pkgs) == len(contents)
    for pkg, whl_content in zip(pkgs, contents):
        assert whl_content
        assert whl_content.path == f"{pkg}-9.8.7-0.editable-py3-none-any.whl"
        with io.BytesIO(whl_content.content) as fp:
            with zipfile.ZipFile(fp, "r") as whl:
                whl_files = whl.namelist()

                pth_path = f"{pkg}__pants__.pth"
                assert pth_path in whl_files
                with whl.open(pth_path) as pth_contents:
                    pth_lines = pth_contents.readlines()

                direct_url_path = f"{pkg}-9.8.7.dist-info/direct_url__pants__.json"
                assert direct_url_path in whl_files
                with whl.open(direct_url_path) as direct_url_contents:
                    direct_url = json.loads(direct_url_contents.read())

        # make sure inferred dep on "a" is included as well
        assert f"{rule_runner.build_root}/root_a\n" in pth_lines
        assert f"{rule_runner.build_root}/root_{pkg}\n" in pth_lines

        assert len(direct_url) == 2
        assert "dir_info" in direct_url
        assert direct_url["dir_info"] == {"editable": True}
        assert "url" in direct_url
        assert direct_url["url"] == f"file://{rule_runner.build_root}/root_{pkg}"
