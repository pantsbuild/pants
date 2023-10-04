# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import cast

import pytest

from pants.core.goals.generate_lockfiles import GenerateLockfileResult, UserGenerateLockfiles
from pants.core.util_rules import source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import DigestContents, FileDigest
from pants.engine.internals.parametrize import Parametrize
from pants.jvm.goals import lockfile
from pants.jvm.goals.lockfile import GenerateJvmLockfile, RequestedJVMUserResolveNames
from pants.jvm.resolve.common import (
    ArtifactRequirement,
    ArtifactRequirements,
    Coordinate,
    Coordinates,
)
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *coursier_fetch_rules(),
            *lockfile.rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *util_rules(),
            QueryRule(UserGenerateLockfiles, [RequestedJVMUserResolveNames]),
            QueryRule(GenerateLockfileResult, [GenerateJvmLockfile]),
        ],
        target_types=[JvmArtifactTarget],
        objects={"parametrize": Parametrize},
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


@maybe_skip_jdk_test
def test_generate_lockfile(rule_runner: RuleRunner) -> None:
    artifacts = ArtifactRequirements(
        [ArtifactRequirement(Coordinate("org.hamcrest", "hamcrest-core", "1.3"))]
    )
    result = rule_runner.request(
        GenerateLockfileResult,
        [
            GenerateJvmLockfile(
                artifacts=artifacts, resolve_name="test", lockfile_dest="lock.txt", diff=False
            )
        ],
    )
    digest_contents = rule_runner.request(DigestContents, [result.digest])
    assert len(digest_contents) == 1

    expected = CoursierResolvedLockfile(
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
        ),
        metadata=JVMLockfileMetadata.new(artifacts),
    )
    assert CoursierResolvedLockfile.from_serialized(digest_contents[0].content) == expected


@maybe_skip_jdk_test
def test_artifact_collision(rule_runner: RuleRunner) -> None:
    # Test that an artifact with fully populated but identical fields can be generated.
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                def mk(name):
                  jvm_artifact(
                      name=name,
                      group='group',
                      artifact='artifact',
                      version='1',
                      jar='jar.jar',
                  )

                mk('one')
                mk('two')
                """
            ),
        }
    )

    result = rule_runner.request(
        UserGenerateLockfiles, [RequestedJVMUserResolveNames(["jvm-default"])]
    )
    # Because each instance of the jar field is unique.
    assert len(cast(GenerateJvmLockfile, result[0]).artifacts) == 2


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
                    resolve=parametrize("a", "b"),
                )

                jvm_artifact(
                    name='opentest4j',
                    group='org.opentest4j',
                    artifact='opentest4j',
                    version='1.2.0',
                    resolve="a",
                )

                jvm_artifact(
                    name='apiguardian-api',
                    group='org.apiguardian',
                    artifact='apiguardian-api',
                    version='1.1.0',
                    resolve="b",
                )
                """
            ),
        }
    )
    rule_runner.set_options(["--jvm-resolves={'a': 'a.lock', 'b': 'b.lock'}"], env_inherit={"PATH"})

    result = rule_runner.request(UserGenerateLockfiles, [RequestedJVMUserResolveNames(["a", "b"])])
    hamcrest_core = ArtifactRequirement(Coordinate("org.hamcrest", "hamcrest-core", "1.3"))
    assert set(result) == {
        GenerateJvmLockfile(
            artifacts=ArtifactRequirements(
                [
                    hamcrest_core,
                    ArtifactRequirement(Coordinate("org.opentest4j", "opentest4j", "1.2.0")),
                ]
            ),
            resolve_name="a",
            lockfile_dest="a.lock",
            diff=False,
        ),
        GenerateJvmLockfile(
            artifacts=ArtifactRequirements(
                [
                    ArtifactRequirement(Coordinate("org.apiguardian", "apiguardian-api", "1.1.0")),
                    hamcrest_core,
                ]
            ),
            resolve_name="b",
            lockfile_dest="b.lock",
            diff=False,
        ),
    }
