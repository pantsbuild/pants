# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import shlex
from dataclasses import dataclass
from textwrap import dedent

import pytest

from pants.core.goals.deploy import Deploy, DeployFieldSet, DeployProcess
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact, PackageFieldSet
from pants.core.goals.publish import (
    PublishFieldSet,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
)
from pants.core.register import rules as core_rules
from pants.engine import process
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import InteractiveProcess
from pants.engine.rules import Get, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    DependenciesRequest,
    StringField,
    StringSequenceField,
    Target,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner


class MockDestinationField(StringField):
    alias = "destination"


class MockRepositoriesField(StringSequenceField):
    alias = "repositories"


class MockDependenciesField(Dependencies):
    pass


class MockPackageTarget(Target):
    alias = "mock_package"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        MockRepositoriesField,
    )


class MockDeployTarget(Target):
    alias = "mock_deploy"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        MockDestinationField,
        MockDependenciesField,
    )


@dataclass(frozen=True)
class MockPublishRequest(PublishRequest):
    pass


@dataclass(frozen=True)
class MockPackageFieldSet(PackageFieldSet):
    required_fields = (MockRepositoriesField,)

    repositories: MockRepositoriesField


@dataclass(frozen=True)
class MockPublishFieldSet(PublishFieldSet):
    publish_request_type = MockPublishRequest
    required_fields = (MockRepositoriesField,)

    repositories: MockRepositoriesField


@dataclass(frozen=True)
class MockDeployFieldSet(DeployFieldSet):
    required_fields = (MockDestinationField,)

    destination: MockDestinationField
    dependencies: MockDependenciesField


@rule
async def mock_package(request: MockPackageFieldSet) -> BuiltPackage:
    artifact = BuiltPackageArtifact(
        relpath=request.address.spec,
        extra_log_lines=tuple(
            [f"test package into: {repo}" for repo in request.repositories.value]
            if request.repositories.value
            else []
        ),
    )
    return BuiltPackage(digest=EMPTY_DIGEST, artifacts=(artifact,))


@rule
async def mock_publish(request: MockPublishRequest) -> PublishProcesses:
    if not request.field_set.repositories.value:
        return PublishProcesses()

    return PublishProcesses(
        PublishPackages(
            names=tuple(
                artifact.relpath
                for pkg in request.packages
                for artifact in pkg.artifacts
                if artifact.relpath
            ),
            process=None
            if repo == "skip"
            else InteractiveProcess(["/bin/sh", "-c", "echo", shlex.quote(repo)]),
            description="(requested)" if repo == "skip" else repo,
        )
        for repo in request.field_set.repositories.value
    )


@rule
async def mock_deploy(field_set: MockDeployFieldSet) -> DeployProcess:
    if not field_set.destination.value:
        return DeployProcess(name=field_set.address.spec, publish_dependencies=(), process=None)

    dependencies = await Get(Targets, DependenciesRequest(field_set.dependencies))
    dest = field_set.destination.value
    return DeployProcess(
        name=field_set.address.spec,
        publish_dependencies=tuple(dependencies),
        description="(requested)" if dest == "skip" else field_set.destination.value,
        process=None
        if dest == "skip"
        else InteractiveProcess(
            ["/bin/sh", "-c", "echo", shlex.quote(dest)], run_in_workspace=True
        ),
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *core_rules(),
            *process.rules(),
            mock_publish,
            mock_deploy,
            mock_package,
            *MockPublishFieldSet.rules(),
            UnionRule(PackageFieldSet, MockPackageFieldSet),
            UnionRule(DeployFieldSet, MockDeployFieldSet),
        ],
        target_types=[MockDeployTarget, MockPackageTarget],
    )


def test_fail_when_no_deploy_targets_matched(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                mock_package(name="foo")
                """
            )
        }
    )

    with pytest.raises(ExecutionError, match="No applicable files or targets matched"):
        rule_runner.run_goal_rule(Deploy, args=("::",))


def test_skip_deploy(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                mock_deploy(name="inst", destination="skip")
                """
            )
        }
    )

    result = rule_runner.run_goal_rule(Deploy, args=("src:inst",))

    assert result.exit_code == 0
    assert "src:inst skipped (requested)" in result.stderr


def test_mocked_deploy(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                mock_package(
                    name="pkg_dependency",
                    repositories=["https://www.example.com"],
                )

                mock_deploy(
                    name="deploy_dependency",
                    destination="foo",
                )

                mock_deploy(
                    name="main",
                    dependencies=[":pkg_dependency", ":deploy_dependency"],
                    destination="bar",
                )
                """
            )
        }
    )

    result = rule_runner.run_goal_rule(Deploy, args=("src:main",))
    assert result.exit_code == 0
    assert not result.stdout

    stderr_lines = result.stderr.splitlines()
    assert stderr_lines[-3:] == [
        "✓ src:deploy_dependency deployed to foo",
        "✓ src:pkg_dependency published to https://www.example.com",
        "✓ src:main deployed to bar",
    ]
