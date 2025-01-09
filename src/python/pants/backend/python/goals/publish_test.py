# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Callable

import pytest

from pants.backend.python.goals.publish import (
    PublishPythonPackageFieldSet,
    PublishPythonPackageRequest,
    rules,
)
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import PythonDistribution, PythonSourcesGeneratorTarget
from pants.backend.python.util_rules import pex_from_targets
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact
from pants.core.goals.publish import PublishPackages, PublishProcesses
from pants.core.util_rules.config_files import rules as config_files_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.process import Process
from pants.testutil.process_util import process_assertion
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    rule_runner = PythonRuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *config_files_rules(),
            *pex_from_targets.rules(),
            *rules(),
            QueryRule(PublishProcesses, [PublishPythonPackageRequest]),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonDistribution],
        objects={"python_artifact": PythonArtifact},
    )
    return set_options(rule_runner)


def set_options(rule_runner: PythonRuleRunner, options: list | None = None) -> PythonRuleRunner:
    rule_runner.set_options(
        options or [],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        env={
            "TWINE_USERNAME": "whoami",
            "TWINE_USERNAME_PYPI": "whoareyou",
            "TWINE_PASSWORD_PYPI": "secret",
        },
    )
    return rule_runner


@pytest.fixture
def packages():
    return (
        BuiltPackage(
            EMPTY_DIGEST,
            (
                BuiltPackageArtifact("my-package-0.1.0.tar.gz"),
                BuiltPackageArtifact("my_package-0.1.0-py3-none-any.whl"),
            ),
        ),
    )


def project_files(
    skip_twine: bool = False, repositories: list[str] = ["@pypi", "@private"]
) -> dict[str, str]:
    return {
        "src/BUILD": dedent(
            f"""\
            python_sources()
            python_distribution(
              name="dist",
              provides=python_artifact(
                name="my-package",
                version="0.1.0",
              ),
              repositories={repositories!r},
              skip_twine={skip_twine},
            )
            """
        ),
        "src/hello.py": """print("hello")""",
        ".pypirc": "",
    }


def request_publish_processes(rule_runner: PythonRuleRunner, packages) -> PublishProcesses:
    tgt = rule_runner.get_target(Address("src", target_name="dist"))
    fs = PublishPythonPackageFieldSet.create(tgt)
    return rule_runner.request(PublishProcesses, [fs._request(packages)])


def assert_package(
    package: PublishPackages,
    expect_names: tuple[str, ...],
    expect_description: str,
    expect_process: Callable[[Process], None] | None,
) -> None:
    assert package.names == expect_names
    assert package.description == expect_description
    if expect_process:
        assert package.process
        expect_process(package.process.process)
    else:
        assert package.process is None


def test_twine_upload(rule_runner, packages) -> None:
    rule_runner.write_files(project_files(skip_twine=False))
    result = request_publish_processes(rule_runner, packages)

    assert len(result) == 2
    assert_package(
        result[0],
        expect_names=(
            "my-package-0.1.0.tar.gz",
            "my_package-0.1.0-py3-none-any.whl",
        ),
        expect_description="@pypi",
        expect_process=process_assertion(
            argv=(
                "./twine.pex_pex_shim.sh",
                "upload",
                "--non-interactive",
                "--config-file=.pypirc",
                "--repository=pypi",
                "my-package-0.1.0.tar.gz",
                "my_package-0.1.0-py3-none-any.whl",
            ),
            env=FrozenDict(
                {
                    "TWINE_USERNAME": "whoareyou",
                    "TWINE_PASSWORD": "secret",
                }
            ),
        ),
    )
    assert_package(
        result[1],
        expect_names=(
            "my-package-0.1.0.tar.gz",
            "my_package-0.1.0-py3-none-any.whl",
        ),
        expect_description="@private",
        expect_process=process_assertion(
            argv=(
                "./twine.pex_pex_shim.sh",
                "upload",
                "--non-interactive",
                "--config-file=.pypirc",
                "--repository=private",
                "my-package-0.1.0.tar.gz",
                "my_package-0.1.0-py3-none-any.whl",
            ),
            env=FrozenDict({"TWINE_USERNAME": "whoami"}),
        ),
    )


def test_skip_twine(rule_runner, packages) -> None:
    rule_runner.write_files(project_files(skip_twine=True))
    result = request_publish_processes(rule_runner, packages)

    assert len(result) == 1
    assert_package(
        result[0],
        expect_names=(
            "my-package-0.1.0.tar.gz",
            "my_package-0.1.0-py3-none-any.whl",
        ),
        expect_description="(by `skip_twine` on src:dist)",
        expect_process=None,
    )

    # Skip twine globally from config option.
    rule_runner.set_options(["--twine-skip"])
    result = request_publish_processes(rule_runner, packages)
    assert len(result) == 0


@pytest.mark.parametrize(
    "options, cert_arg",
    [
        pytest.param(
            [],
            None,
            id="No ca cert",
        ),
        pytest.param(
            ["--twine-ca-certs-path={}"],
            "--cert=ca_certs.pem",
            id="[twine].ca_certs_path",
        ),
        # This test needs a working ca bundle to work. Verified manually for now.
        # pytest.param(
        #     ["--ca-certs-path={}"],
        #     "--cert=ca_certs.pem",
        #     id="[GLOBAL].ca_certs_path",
        # ),
    ],
)
def test_twine_cert_arg(rule_runner, packages, options, cert_arg) -> None:
    ca_cert_path = rule_runner.write_files({"conf/ca_certs.pem": ""})[0]
    rule_runner.write_files(project_files(repositories=["@private"]))
    set_options(rule_runner, [opt.format(ca_cert_path) for opt in options])
    result = request_publish_processes(rule_runner, packages)
    assert len(result) == 1
    process = result[0].process
    assert process
    if cert_arg:
        assert cert_arg in process.process.argv
    else:
        assert not any(arg.startswith("--cert") for arg in process.process.argv)
