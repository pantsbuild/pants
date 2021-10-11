# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent

import pytest

from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.register import rules as python_rules
from pants.backend.python.target_types import PythonDistribution, PythonLibrary
from pants.core.goals.publish import (
    Publish,
    PublishFieldSet,
    PublishPackages,
    PublishProcesses,
    PublishRequest,
    rules,
)
from pants.core.register import rules as core_rules
from pants.engine.process import InteractiveProcess
from pants.engine.rules import rule
from pants.engine.target import StringSequenceField
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
            process=None if repo == "skip" else InteractiveProcess(["echo", repo]),
            description="(requested)" if repo == "skip" else repo,
        )
        for repo in request.field_set.repositories.value
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *core_rules(),
            *python_rules(),
            *rules(),
            mock_publish,
            PythonDistribution.register_plugin_field(MockRepositoriesField),
            *PublishTestFieldSet.rules(),
        ],
        target_types=[PythonLibrary, PythonDistribution],
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
    assert "my-package-0.1.0.tar.gz skipped (requested)." in result.stderr
    assert "my_package-0.1.0-py3-none-any.whl skipped (requested)." in result.stderr


@pytest.mark.skip("Can not run interactive process from test..?")
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
    assert "my-package-0.1.0.tar.gz published." in result.stderr
    assert "my_package-0.1.0-py3-none-any.whl published." in result.stderr
    assert "mocked-repo" in result.stdout
