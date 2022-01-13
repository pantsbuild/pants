# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.core.util_rules import source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import FileDigest
from pants.jvm.goals.coursier import CoursierResolve
from pants.jvm.goals.coursier import rules as coursier_goal_rules
from pants.jvm.resolve.common import Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import RuleRunner

HAMCREST_BUILD_FILE = dedent(
    """\
    jvm_artifact(
        name='hamcrest',
        group='org.hamcrest',
        artifact='hamcrest-core',
        version="1.3",
    )
    """
)
HAMCREST_EXPECTED_LOCKFILE = CoursierResolvedLockfile(
    entries=(
        CoursierLockfileEntry(
            coord=Coordinate(
                group="org.hamcrest",
                artifact="hamcrest-core",
                version="1.3",
            ),
            file_name="org.hamcrest_hamcrest-core_1.3.jar",
            direct_dependencies=Coordinates([]),
            dependencies=Coordinates([]),
            file_digest=FileDigest(
                fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                serialized_bytes_length=45024,
            ),
        ),
    )
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *coursier_fetch_rules(),
            *coursier_goal_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *util_rules(),
        ],
        target_types=[JvmArtifactTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


@maybe_skip_jdk_test
def test_creates_missing_lockfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": HAMCREST_BUILD_FILE})
    result = rule_runner.run_goal_rule(CoursierResolve, args=[], env_inherit={"PATH"})
    assert result.exit_code == 0
    assert result.stderr == "Updated lockfile at: 3rdparty/jvm/default.lock\n"
    assert (
        Path(rule_runner.build_root, "3rdparty/jvm/default.lock").read_bytes()
        == HAMCREST_EXPECTED_LOCKFILE.to_json()
    )


@maybe_skip_jdk_test
def test_noop_does_not_touch_lockfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": HAMCREST_BUILD_FILE,
            "3rdparty/jvm/default.lock": HAMCREST_EXPECTED_LOCKFILE.to_json().decode("utf-8"),
        }
    )
    result = rule_runner.run_goal_rule(CoursierResolve, args=[], env_inherit={"PATH"})
    assert result.exit_code == 0
    assert result.stderr == ""
    assert (
        Path(rule_runner.build_root, "3rdparty/jvm/default.lock").read_bytes()
        == HAMCREST_EXPECTED_LOCKFILE.to_json()
    )


@maybe_skip_jdk_test
def test_updates_lockfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"BUILD": HAMCREST_BUILD_FILE, "3rdparty/jvm/default.lock": "[]"})
    result = rule_runner.run_goal_rule(CoursierResolve, args=[], env_inherit={"PATH"})
    assert result.exit_code == 0
    assert result.stderr == "Updated lockfile at: 3rdparty/jvm/default.lock\n"
    assert (
        Path(rule_runner.build_root, "3rdparty/jvm/default.lock").read_bytes()
        == HAMCREST_EXPECTED_LOCKFILE.to_json()
    )


@maybe_skip_jdk_test
def test_multiple_resolves(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name='hamcrest',
                    group='org.hamcrest',
                    artifact='hamcrest-core',
                    version="1.3",
                    compatible_resolves=["a", "b"],
                )
                jvm_artifact(
                    name='opentest4j',
                    group='org.opentest4j',
                    artifact='opentest4j',
                    version='1.2.0',
                    compatible_resolves=["a"],
                )
                jvm_artifact(
                    name='apiguardian-api',
                    group='org.apiguardian',
                    artifact='apiguardian-api',
                    version='1.1.0',
                    compatible_resolves=["b"],
                )
                """
            ),
        }
    )
    result = rule_runner.run_goal_rule(
        CoursierResolve,
        args=["--jvm-resolves={'a': 'a.lockfile', 'b': 'b.lockfile'}"],
        env_inherit={"PATH"},
    )
    assert result.exit_code == 0
    assert "Updated lockfile at: a.lockfile" in result.stderr
    assert "Updated lockfile at: b.lockfile" in result.stderr

    expected_lockfile_a = CoursierResolvedLockfile(
        entries=(
            HAMCREST_EXPECTED_LOCKFILE.entries[0],
            CoursierLockfileEntry(
                coord=Coordinate(group="org.opentest4j", artifact="opentest4j", version="1.2.0"),
                file_name="org.opentest4j_opentest4j_1.2.0.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="58812de60898d976fb81ef3b62da05c6604c18fd4a249f5044282479fc286af2",
                    serialized_bytes_length=7653,
                ),
            ),
        )
    )
    assert Path(rule_runner.build_root, "a.lockfile").read_bytes() == expected_lockfile_a.to_json()

    expected_lockfile_b = CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.apiguardian", artifact="apiguardian-api", version="1.1.0"
                ),
                file_name="org.apiguardian_apiguardian-api_1.1.0.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="a9aae9ff8ae3e17a2a18f79175e82b16267c246fbbd3ca9dfbbb290b08dcfdd4",
                    serialized_bytes_length=2387,
                ),
            ),
            HAMCREST_EXPECTED_LOCKFILE.entries[0],
        )
    )
    assert Path(rule_runner.build_root, "b.lockfile").read_bytes() == expected_lockfile_b.to_json()
