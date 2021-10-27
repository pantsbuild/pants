# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.java.target_types import JavaSourcesGeneratorTarget
from pants.core.target_types import ResourcesGeneratorTarget
from pants.core.target_types import rules as core_rules
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
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner, logging
from pants.util.logging import LogLevel

HAMCREST_COORD = Coordinate(
    group="org.hamcrest",
    artifact="hamcrest-core",
    version="1.3",
)


ARGS = [
    """--jvm-resolves={"test": "coursier_resolve.lockfile"}""",
    """--jvm-default-resolve=test""",
    """--coursier-resolve-names=["test"]""",
]


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *core_rules(),
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_goal_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *util_rules(),
        ],
        target_types=[
            JvmDependencyLockfile,
            JvmArtifact,
            ResourcesGeneratorTarget,
            JavaSourcesGeneratorTarget,
        ],
    )
    rule_runner.set_options(args=ARGS, env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@logging(level=LogLevel.DEBUG)
@maybe_skip_jdk_test
def test_coursier_resolve_creates_missing_lockfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'here_to_provide_dependencies',
                    dependencies = [
                        ':org.hamcrest_hamcrest-core',
                    ],
                )

                jvm_artifact(
                    name = 'org.hamcrest_hamcrest-core',
                    group = 'org.hamcrest',
                    artifact = 'hamcrest-core',
                    version = "1.3",
                )
                """
            ),
        }
    )
    result = rule_runner.run_goal_rule(CoursierResolve, args=ARGS, env_inherit=PYTHON_BOOTSTRAP_ENV)
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


@logging(level=LogLevel.DEBUG)
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
                java_sources(
                    name = 'here_to_provide_dependencies',
                    dependencies = [
                        ':org.hamcrest_hamcrest-core',
                    ],
                )

                jvm_artifact(
                    name = 'org.hamcrest_hamcrest-core',
                    group = 'org.hamcrest',
                    artifact = 'hamcrest-core',
                    version = "1.3",
                )
                coursier_lockfile(
                    name='example-lockfile',
                    source="coursier_resolve.lockfile",
                )
                """
            ),
            "coursier_resolve.lockfile": expected_lockfile.to_json().decode("utf-8"),
        }
    )
    result = rule_runner.run_goal_rule(CoursierResolve, args=ARGS, env_inherit=PYTHON_BOOTSTRAP_ENV)
    assert result.exit_code == 0
    assert result.stderr == ""


@logging(level=LogLevel.DEBUG)
@maybe_skip_jdk_test
def test_coursier_resolve_updates_lockfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'here_to_provide_dependencies',
                    dependencies = [
                        ':org.hamcrest_hamcrest-core',
                    ],
                    sources = ["*.txt"],
                )

                jvm_artifact(
                    name = 'org.hamcrest_hamcrest-core',
                    group = 'org.hamcrest',
                    artifact = 'hamcrest-core',
                    version = "1.3",
                )
                coursier_lockfile(
                    name = 'example-lockfile',
                )
                """
            ),
            "coursier_resolve.lockfile": "[]",
        }
    )
    result = rule_runner.run_goal_rule(CoursierResolve, args=ARGS, env_inherit=PYTHON_BOOTSTRAP_ENV)
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


@logging(level=LogLevel.DEBUG)
@maybe_skip_jdk_test
def test_coursier_resolve_updates_bogus_lockfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_sources(
                    name = 'here_to_provide_dependencies',
                    dependencies = [
                        ':org.hamcrest_hamcrest-core',
                    ],
                    sources = ["*.txt"],
                )

                jvm_artifact(
                    name = 'org.hamcrest_hamcrest-core',
                    group = 'org.hamcrest',
                    artifact = 'hamcrest-core',
                    version = "1.3",
                )
                coursier_lockfile(
                    name = 'example-lockfile',
                )
                """
            ),
            "coursier_resolve.lockfile": "]bad json[",
        }
    )
    result = rule_runner.run_goal_rule(CoursierResolve, args=ARGS, env_inherit=PYTHON_BOOTSTRAP_ENV)
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
