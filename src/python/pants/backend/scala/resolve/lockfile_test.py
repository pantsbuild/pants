# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.scala.dependency_inference import rules as scala_dep_inf_rules
from pants.backend.scala.resolve.lockfile import rules as scala_lockfile_rules
from pants.core.goals.generate_lockfiles import GenerateLockfileResult
from pants.core.util_rules import archive, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import DigestContents, FileDigest
from pants.engine.internals import graph
from pants.jvm import jdk_rules
from pants.jvm.goals import lockfile
from pants.jvm.goals.lockfile import RequestedJVMserResolveNames
from pants.jvm.resolve.common import ArtifactRequirements, Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.jvm_tool import rules as coursier_jvm_tool_rules
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *scala_lockfile_rules(),
            *scala_dep_inf_rules.rules(),
            *jdk_rules.rules(),
            *coursier_fetch_rules(),
            *coursier_jvm_tool_rules(),
            *lockfile.rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *util_rules(),
            *archive.rules(),
            *graph.rules(),
            # QueryRule(UserGenerateLockfiles, [RequestedJVMserResolveNames]),
            QueryRule(GenerateLockfileResult, [RequestedJVMserResolveNames]),
        ],
        target_types=[JvmArtifactTarget],
    )
    rule_runner.set_options(['--scala-version-for-resolve={"foo":"2.13.8"}'], env_inherit={"PATH"})
    return rule_runner


@maybe_skip_jdk_test
def test_scala_library_added_to_resolve(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "scala_sources(resolve='foo')",
            "foo/Foo.scala": "package foo",
        }
    )
    artifacts = ArtifactRequirements()
    result = rule_runner.request(
        GenerateLockfileResult,
        [RequestedJVMserResolveNames(["foo"])],
    )
    digest_contents = rule_runner.request(DigestContents, [result.digest])
    assert len(digest_contents) == 1

    expected = CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.scala-lang",
                    artifact="scala-library",
                    version="2.13.8",
                ),
                file_name="",
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
