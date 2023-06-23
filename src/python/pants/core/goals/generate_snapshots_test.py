# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from pants.core.goals import generate_snapshots
from pants.core.goals.generate_snapshots import (
    GenerateSnapshots,
    GenerateSnapshotsFieldSet,
    GenerateSnapshotsResult,
)
from pants.engine.fs import CreateDigest, FileContent, Snapshot
from pants.engine.rules import Get, rule
from pants.engine.target import StringField, Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner


class MockRequiredField(StringField):
    alias = "required"
    required = True


class MockTarget(Target):
    alias = "mock"
    core_fields = (MockRequiredField,)


@dataclass(frozen=True)
class MockGenerateSnapshotsFieldSet(GenerateSnapshotsFieldSet):
    required_fields = (MockRequiredField,)

    required: MockRequiredField


MOCK_SNAPSHOT_FILENAME = "mock_snapshot.snap"
MOCK_SNAPSHOT_CONTENT = "mocked snapshot"


@rule
async def mock_generate_snapshots(
    field_set: MockGenerateSnapshotsFieldSet,
) -> GenerateSnapshotsResult:
    snapshot = await Get(
        Snapshot,
        CreateDigest(
            [FileContent(path=MOCK_SNAPSHOT_FILENAME, content=MOCK_SNAPSHOT_CONTENT.encode())]
        ),
    )
    return GenerateSnapshotsResult(snapshot)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *generate_snapshots.rules(),
            mock_generate_snapshots,
            UnionRule(GenerateSnapshotsFieldSet, MockGenerateSnapshotsFieldSet),
        ],
        target_types=[MockTarget],
    )


def test_write_snapshots_to_worksapce(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"src/BUILD": """mock(name="foo", required="blah")"""})
    result = rule_runner.run_goal_rule(GenerateSnapshots, args=("src:foo",))

    assert result.exit_code == 0
    expected_snapshot = Path(rule_runner.build_root, MOCK_SNAPSHOT_FILENAME)
    expected_snapshot.read_text() == MOCK_SNAPSHOT_CONTENT
