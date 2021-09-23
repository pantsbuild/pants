# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import FileDigest
from pants.jvm.goals.coursier import CoursierResolve
from pants.jvm.goals.coursier import rules as coursier_goal_rules
from pants.jvm.resolve.coursier_fetch import (
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmArtifact, JvmDependencyLockfile
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import RuleRunner

HAMCREST_COORD = Coordinate(
    group="org.hamcrest",
    artifact="hamcrest-core",
    version="1.3",
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        preserve_tmpdirs=True,
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_goal_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *util_rules(),
        ],
        target_types=[JvmDependencyLockfile, JvmArtifact],
    )


@maybe_skip_jdk_test
def test_coursier_resolve_creates_missing_lockfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = 'org.hamcrest_hamcrest-core',
                    group = 'org.hamcrest',
                    artifact = 'hamcrest-core',
                    version = "1.3",
                )
                coursier_lockfile(
                    name = 'example-lockfile',
                    requirements = [
                        ':org.hamcrest_hamcrest-core',
                    ],
                )
                """
            ),
        }
    )
    result = rule_runner.run_goal_rule(CoursierResolve, args=["::"])
    assert result.exit_code == 0
    assert result.stderr == "Updated lockfile at: coursier_resolve.lockfile\n"
    expected_lockfile = CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=HAMCREST_COORD,
                file_name="hamcrest-core-1.3.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                    serialized_bytes_length=45024,
                ),
            ),
        )
    )
    assert (
        Path(rule_runner.build_root, "coursier_resolve.lockfile").read_bytes()
        == expected_lockfile.to_json()
    )


@maybe_skip_jdk_test
def test_coursier_resolve_noop_does_not_touch_lockfile(rule_runner: RuleRunner) -> None:
    expected_lockfile = CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=HAMCREST_COORD,
                file_name="hamcrest-core-1.3.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                    serialized_bytes_length=45024,
                ),
            ),
        )
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = 'org.hamcrest_hamcrest-core',
                    group = 'org.hamcrest',
                    artifact = 'hamcrest-core',
                    version = "1.3",
                )
                coursier_lockfile(
                    name = 'example-lockfile',
                    requirements = [
                        ':org.hamcrest_hamcrest-core',
                    ],
                    sources = [
                        "coursier_resolve.lockfile",
                    ],
                )
                """
            ),
            "coursier_resolve.lockfile": expected_lockfile.to_json().decode("utf-8"),
        }
    )
    result = rule_runner.run_goal_rule(CoursierResolve, args=["::"])
    assert result.exit_code == 0
    assert result.stderr == ""


@maybe_skip_jdk_test
def test_coursier_resolve_updates_lockfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = 'org.hamcrest_hamcrest-core',
                    group = 'org.hamcrest',
                    artifact = 'hamcrest-core',
                    version = "1.3",
                )
                coursier_lockfile(
                    name = 'example-lockfile',
                    requirements = [
                        ':org.hamcrest_hamcrest-core',
                    ],
                )
                """
            ),
            "coursier_resolve.lockfile": "[]",
        }
    )
    result = rule_runner.run_goal_rule(CoursierResolve, args=["::"])
    assert result.exit_code == 0
    assert result.stderr == "Updated lockfile at: coursier_resolve.lockfile\n"
    expected_lockfile = CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=HAMCREST_COORD,
                file_name="hamcrest-core-1.3.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                    serialized_bytes_length=45024,
                ),
            ),
        )
    )
    assert (
        Path(rule_runner.build_root, "coursier_resolve.lockfile").read_bytes()
        == expected_lockfile.to_json()
    )


@maybe_skip_jdk_test
def test_coursier_resolve_updates_bogus_lockfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = 'org.hamcrest_hamcrest-core',
                    group = 'org.hamcrest',
                    artifact = 'hamcrest-core',
                    version = "1.3",
                )
                coursier_lockfile(
                    name = 'example-lockfile',
                    requirements = [
                        ':org.hamcrest_hamcrest-core',
                    ],
                )
                """
            ),
            "coursier_resolve.lockfile": "]bad json[",
        }
    )
    result = rule_runner.run_goal_rule(CoursierResolve, args=["::"])
    assert result.exit_code == 0
    assert result.stderr == "Updated lockfile at: coursier_resolve.lockfile\n"
    expected_lockfile = CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=HAMCREST_COORD,
                file_name="hamcrest-core-1.3.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                    serialized_bytes_length=45024,
                ),
            ),
        )
    )
    assert (
        Path(rule_runner.build_root, "coursier_resolve.lockfile").read_bytes()
        == expected_lockfile.to_json()
    )
