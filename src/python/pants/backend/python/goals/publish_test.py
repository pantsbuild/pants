# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.goals.publish import PublishToPyPiFieldSet, PublishToPyPiRequest, rules
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import PythonDistribution, PythonLibrary
from pants.backend.python.util_rules import pex_from_targets
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact
from pants.core.goals.publish import PublishPackageProcesses, PublishPackagesProcesses
from pants.core.util_rules.config_files import rules as config_files_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files_rules(),
            *pex_from_targets.rules(),
            *rules(),
            QueryRule(PublishPackagesProcesses, [PublishToPyPiRequest]),
        ],
        target_types=[PythonLibrary, PythonDistribution],
        objects={"python_artifact": PythonArtifact},
    )
    rule_runner.set_options(
        [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        env={"TWINE_PASSWORD_PYPI": "secret"},
    )
    return rule_runner


@pytest.fixture
def packages():
    return (
        BuiltPackage(
            EMPTY_DIGEST,
            (
                BuiltPackageArtifact("my-package-0.1.0.tar.gz"),
                BuiltPackageArtifact("my-package-0.1.0.whl"),
            ),
        ),
    )


def project_files(skip_twine: bool) -> dict[str, str]:
    return {
        "src/BUILD": dedent(
            f"""\
            python_library()
            python_distribution(
              name="dist",
              provides=python_artifact(
                name="my-package",
                version="0.1.0",
              ),
              pypi_repositories=["@pypi", "@private"],
              skip_twine={skip_twine},
            )
            """
        ),
        "src/hello.py": """print("hello")""",
        ".pypirc": "",
    }


def assert_package_processes(
    package: PublishPackageProcesses,
    *expect_processes,
    expect_names: tuple[str, ...],
    expect_description: str,
) -> None:
    assert package.names == expect_names
    assert package.description == expect_description
    assert len(package.processes) == len(expect_processes)
    processes = iter(package.processes)
    for assert_process in expect_processes:
        assert_process(next(processes))


def process_assertion(**assertions):
    def assert_process(process):
        for attr, expected in assertions.items():
            assert getattr(process, attr) == expected

    return assert_process


def test_twine_upload(rule_runner, packages) -> None:
    rule_runner.write_files(project_files(skip_twine=False))

    tgt = rule_runner.get_target(Address("src", target_name="dist"))
    fs = PublishToPyPiFieldSet.create(tgt)
    result = rule_runner.request(PublishPackagesProcesses, [fs.request(packages)])

    assert len(result.packages) == 2
    assert_package_processes(
        result.packages[0],
        process_assertion(
            argv=(
                "./twine.pex_pex_shim.sh",
                "upload",
                "--non-interactive",
                "--config-file=.pypirc",
                "--repository=pypi",
                "my-package-0.1.0.tar.gz",
                "my-package-0.1.0.whl",
            ),
            env=FrozenDict({"TWINE_PASSWORD": "secret"}),
        ),
        expect_names=(
            "my-package-0.1.0.tar.gz",
            "my-package-0.1.0.whl",
        ),
        expect_description="@pypi",
    )
    assert_package_processes(
        result.packages[1],
        process_assertion(
            argv=(
                "./twine.pex_pex_shim.sh",
                "upload",
                "--non-interactive",
                "--config-file=.pypirc",
                "--repository=private",
                "my-package-0.1.0.tar.gz",
                "my-package-0.1.0.whl",
            ),
            env=FrozenDict(),
        ),
        expect_names=(
            "my-package-0.1.0.tar.gz",
            "my-package-0.1.0.whl",
        ),
        expect_description="@private",
    )


def test_skip_twine(rule_runner, packages) -> None:
    rule_runner.write_files(project_files(skip_twine=True))

    tgt = rule_runner.get_target(Address("src", target_name="dist"))
    fs = PublishToPyPiFieldSet.create(tgt)
    result = rule_runner.request(PublishPackagesProcesses, [fs.request(packages)])

    assert len(result.packages) == 1
    assert_package_processes(
        result.packages[0],
        expect_names=(
            "my-package-0.1.0.tar.gz",
            "my-package-0.1.0.whl",
        ),
        expect_description="(by `skip_twine` on src:dist)",
    )

    # Skip twine globally from config option.
    rule_runner.set_options(["--twine-skip"])
    result = rule_runner.request(PublishPackagesProcesses, [fs.request(packages)])
    assert len(result.packages) == 0
