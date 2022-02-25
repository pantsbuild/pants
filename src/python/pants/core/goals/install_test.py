# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from textwrap import dedent

import pytest
from pants.engine import process
from pants.engine.process import InteractiveProcess
from pants.engine.rules import rule
from pants.engine.target import COMMON_TARGET_FIELDS, StringSequenceField, Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner

from pants.core.goals.install import Install, InstallFieldSet, InstallProcess, InstallProcesses


class MockDestinationsField(StringSequenceField):
    alias = "destinations"


class MockInstallTarget(Target):
    alias = "mock_target"
    core_fields = (*COMMON_TARGET_FIELDS, MockDestinationsField)


@dataclass(frozen=True)
class MockInstallFieldSet(InstallFieldSet):
    required_fields = (MockDestinationsField,)

    destinations: MockDestinationsField


@rule
async def mock_install(field_set: MockInstallFieldSet) -> InstallProcesses:
    if not field_set.destinations.value:
        return InstallProcesses()

    return InstallProcesses(
        InstallProcess(
            name="test-install",
            process=None
            if dest == "skip"
            else InteractiveProcess(["echo", dest], run_in_workspace=True),
            description="(requested)" if dest == "skip" else dest,
        )
        for dest in field_set.destinations.value
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *core_rules(),
            *process.rules(),
            mock_install,
            UnionRule(InstallFieldSet, MockInstallFieldSet),
        ],
        target_types=[MockInstallTarget],
    )


def test_noop(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                mock_target(name="inst")
                """
            )
        }
    )

    result = rule_runner.run_goal_rule(Install, args=("src:inst",))

    assert result.exit_code == 0
    assert "Nothing installed." in result.stderr


def test_skip_install(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                mock_target(name="inst", destinations=["skip"])
                """
            )
        }
    )

    result = rule_runner.run_goal_rule(Install, args=("src:inst",))

    assert result.exit_code == 0
    assert "test-install skipped (requested)." in result.stderr
