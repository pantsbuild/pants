# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from dataclasses import dataclass
from textwrap import dedent

import pytest

from pants.backend.python.goals import package_dists
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import PythonDistribution, PythonSourcesGeneratorTarget
from pants.backend.python.target_types_rules import rules as python_target_type_rules
from pants.core.goals import package, publish
from pants.core.goals.publish import (
    CheckSkipRequest,
    CheckSkipResult,
    Publish,
    PublishFieldSet,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.engine.process import Process, ProcessCacheScope
from pants.engine.rules import rule
from pants.engine.target import StringSequenceField
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner


class MockRepositoriesField(StringSequenceField):
    alias = "repositories"


@dataclass(frozen=True)
class MockPublishRequest(PublishRequest):
    pass


@dataclass(frozen=True)
class PublishTestFieldSet(PublishFieldSet):
    publish_request_type = MockPublishRequest
    required_fields = (MockRepositoriesField,)

    repositories: MockRepositoriesField

    def check_skip_request(self, package_fs: package.PackageFieldSet) -> TestPreemptiveSkipRequest:
        return TestPreemptiveSkipRequest(publish_fs=self, package_fs=package_fs)


class TestPreemptiveSkipRequest(CheckSkipRequest[PublishTestFieldSet]):
    pass


@rule
async def mock_check_if_skip(request: TestPreemptiveSkipRequest) -> CheckSkipResult:
    if not request.publish_fs.repositories.value:
        return CheckSkipResult.skip(names=[], data=request.publish_fs.get_output_data())
    if request.publish_fs.repositories.value == ("skip-package",):
        return CheckSkipResult.skip(skip_packaging_only=True)
    if request.publish_fs.repositories.value == ("skip",):
        return CheckSkipResult.skip(
            names=["my_package-0.1.0-py3-none-any.whl", "my_package-0.1.0.tar.gz"],
            description="(requested)",
            data=request.publish_fs.get_output_data(),
        )
    return CheckSkipResult.no_skip()


@rule
async def mock_publish(request: MockPublishRequest) -> PublishProcesses:
    assert len(request.field_set.repositories.value) > 0
    names = (
        ("my_other_package-0.1.0-py3-none-any.whl", "my_other_package-0.1.0.tar.gz")
        if request.field_set.repositories.value == ("skip-package",)
        else tuple(
            artifact.relpath
            for pkg in request.packages
            for artifact in pkg.artifacts
            if artifact.relpath
        )
    )
    return PublishProcesses(
        PublishPackages(
            names=names,
            process=(
                None
                if repo == "skip"
                else Process(
                    ["/bin/echo", repo],
                    cache_scope=ProcessCacheScope.PER_SESSION,
                    description="mock publish",
                )
            ),
            description="(requested)" if repo == "skip" else repo,
        )
        for repo in request.field_set.repositories.value
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *package.rules(),
            *publish.rules(),
            *package_dists.rules(),
            *python_target_type_rules(),
            mock_check_if_skip,
            mock_publish,
            PythonDistribution.register_plugin_field(MockRepositoriesField),
            *PublishTestFieldSet.rules(),
            UnionRule(CheckSkipRequest, TestPreemptiveSkipRequest),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonDistribution],
        objects={"python_artifact": PythonArtifact},
    )


def test_noop(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                python_sources()
                python_distribution(
                  name="dist",
                  provides=python_artifact(
                    name="my-package",
                    version="0.1.0",
                  ),
                )
                """
            ),
        }
    )

    result = rule_runner.run_goal_rule(
        Publish,
        args=("src:dist",),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0
    assert "Nothing published." in result.stderr


def test_skipped_publish(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                python_sources()
                python_distribution(
                  name="dist",
                  provides=python_artifact(
                    name="my-package",
                    version="0.1.0",
                  ),
                  repositories=["skip"],
                )
                """
            ),
        }
    )

    result = rule_runner.run_goal_rule(
        Publish,
        args=("src:dist",),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0
    assert "my_package-0.1.0.tar.gz skipped (requested)." in result.stderr
    assert "my_package-0.1.0-py3-none-any.whl skipped (requested)." in result.stderr


def test_skip_package_only(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                python_sources()
                python_distribution(
                  name="dist",
                  provides=python_artifact(
                    name="my-package",
                    version="0.1.0",
                  ),
                  repositories=["skip-package"],
                )
                """
            ),
        }
    )
    result = rule_runner.run_goal_rule(
        Publish,
        args=("src:dist",),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0
    assert "my_other_package-0.1.0.tar.gz published to skip-package." in result.stderr
    assert "my_other_package-0.1.0-py3-none-any.whl published to skip-package." in result.stderr


def test_structured_output(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                python_sources()
                python_distribution(
                  name="dist",
                  provides=python_artifact(
                    name="my-package",
                    version="0.1.0",
                  ),
                  repositories=["skip"],
                )
                """
            ),
        }
    )

    result = rule_runner.run_goal_rule(
        Publish,
        args=(
            "--output=published.json",
            "src:dist",
        ),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0
    assert "my_package-0.1.0.tar.gz skipped (requested)." in result.stderr
    assert "my_package-0.1.0-py3-none-any.whl skipped (requested)." in result.stderr

    expected = [
        {
            "names": [
                "my_package-0.1.0-py3-none-any.whl",
                "my_package-0.1.0.tar.gz",
            ],
            "published": False,
            "status": "skipped (requested)",
            "target": "src:dist",
        },
    ]

    with rule_runner.pushd():
        with open("published.json") as fd:
            data = json.load(fd)
            assert data == expected


def test_mocked_publish(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                python_sources()
                python_distribution(
                  name="dist",
                  provides=python_artifact(
                    name="my-package",
                    version="0.1.0",
                  ),
                  repositories=["mocked-repo"],
                )
                """
            ),
        }
    )

    result = rule_runner.run_goal_rule(
        Publish,
        args=("src:dist",),
        env_inherit={"HOME", "PATH", "PYENV_ROOT"},
    )

    assert result.exit_code == 0
    assert "my_package-0.1.0.tar.gz published to mocked-repo." in result.stderr
    assert "my_package-0.1.0-py3-none-any.whl published to mocked-repo." in result.stderr
