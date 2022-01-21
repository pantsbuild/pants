# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from textwrap import dedent

import pytest

from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.goals.generate_lockfiles import GenerateLockfileResult, UserGenerateLockfiles
from pants.core.util_rules import source_files
from pants.engine.fs import DigestContents, FileDigest
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import ProcessExecutionFailure
from pants.engine.target import Targets
from pants.jvm.goals import lockfile
from pants.jvm.goals.lockfile import GenerateJvmLockfile, RequestedJVMserResolveNames
from pants.jvm.resolve import user_resolves
from pants.jvm.resolve.common import (
    ArtifactRequirement,
    ArtifactRequirements,
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.jvm.target_types import JvmArtifactJarSourceField, JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *lockfile.rules(),
            *user_resolves.rules(),
            *source_files.rules(),
            *util_rules(),
            QueryRule(Targets, [AddressSpecs]),
            QueryRule(CoursierResolvedLockfile, [ArtifactRequirements]),
            QueryRule(UserGenerateLockfiles, [RequestedJVMserResolveNames]),
            QueryRule(GenerateLockfileResult, [GenerateJvmLockfile]),
        ],
        target_types=[JvmArtifactTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


HAMCREST_COORD = Coordinate(
    group="org.hamcrest",
    artifact="hamcrest-core",
    version="1.3",
)


@maybe_skip_jdk_test
def test_empty_resolve(rule_runner: RuleRunner) -> None:
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [ArtifactRequirements([])],
    )
    assert resolved_lockfile == CoursierResolvedLockfile(entries=())


# TODO(#11928): Make all of these tests more hermetic and not dependent on having a network connection.


@maybe_skip_jdk_test
def test_resolve_with_no_deps(rule_runner: RuleRunner) -> None:
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [ArtifactRequirements.from_coordinates([HAMCREST_COORD])],
    )
    assert resolved_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=HAMCREST_COORD,
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


@maybe_skip_jdk_test
def test_resolve_with_transitive_deps(rule_runner: RuleRunner) -> None:
    junit_coord = Coordinate(group="junit", artifact="junit", version="4.13.2")
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [
            ArtifactRequirements.from_coordinates([junit_coord]),
        ],
    )

    assert resolved_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=junit_coord,
                file_name="junit_junit_4.13.2.jar",
                direct_dependencies=Coordinates([HAMCREST_COORD]),
                dependencies=Coordinates([HAMCREST_COORD]),
                file_digest=FileDigest(
                    fingerprint="8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3",
                    serialized_bytes_length=384581,
                ),
            ),
            CoursierLockfileEntry(
                coord=HAMCREST_COORD,
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


@maybe_skip_jdk_test
def test_resolve_with_inexact_coord(rule_runner: RuleRunner) -> None:
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [
            # Note the open-ended coordinate here.  We will still resolve this for the user, but the result
            # will be exact and pinned.  As noted above, this is an especially brittle unit test, but version
            # 4.8 was chosen because it has multiple patch versions and no new versions have been uploaded
            # to 4.8.x in over a decade.
            ArtifactRequirements.from_coordinates(
                [Coordinate(group="junit", artifact="junit", version="4.8+")]
            ),
        ],
    )

    assert resolved_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=Coordinate(group="junit", artifact="junit", version="4.8.2"),
                file_name="junit_junit_4.8.2.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="a2aa2c3bb2b72da76c3e6a71531f1eefdc350494819baf2b1d80d7146e020f9e",
                    serialized_bytes_length=237344,
                ),
            ),
        )
    )


@maybe_skip_jdk_test
def test_resolve_conflicting(rule_runner: RuleRunner) -> None:
    with engine_error(
        ProcessExecutionFailure, contains="Resolution error: Unsatisfied rule Strict(junit:junit)"
    ):
        rule_runner.request(
            CoursierResolvedLockfile,
            [
                ArtifactRequirements.from_coordinates(
                    [
                        Coordinate(group="junit", artifact="junit", version="4.8.1"),
                        Coordinate(group="junit", artifact="junit", version="4.8.2"),
                    ]
                ),
            ],
        )


@maybe_skip_jdk_test
def test_resolve_with_packaging(rule_runner: RuleRunner) -> None:
    # Tests that an artifact pom which actually reports packaging ends up with proper version and
    # packaging information.
    #   see https://github.com/pantsbuild/pants/issues/13986
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [
            ArtifactRequirements.from_coordinates(
                [Coordinate(group="org.bouncycastle", artifact="bcutil-jdk15on", version="1.70")]
            ),
        ],
    )

    assert resolved_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.bouncycastle",
                    artifact="bcprov-jdk15on",
                    version="1.70",
                    packaging="jar",
                    strict=True,
                ),
                file_name="org.bouncycastle_bcprov-jdk15on_jar_1.70.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    "8f3c20e3e2d565d26f33e8d4857a37d0d7f8ac39b62a7026496fcab1bdac30d4", 5867298
                ),
                remote_url=None,
                pants_address=None,
            ),
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.bouncycastle",
                    artifact="bcutil-jdk15on",
                    version="1.70",
                    packaging="jar",
                    strict=True,
                ),
                file_name="org.bouncycastle_bcutil-jdk15on_1.70.jar",
                direct_dependencies=Coordinates(
                    [
                        Coordinate(
                            group="org.bouncycastle",
                            artifact="bcprov-jdk15on",
                            version="1.70",
                            packaging="jar",
                            strict=True,
                        )
                    ]
                ),
                dependencies=Coordinates(
                    [
                        Coordinate(
                            group="org.bouncycastle",
                            artifact="bcprov-jdk15on",
                            version="1.70",
                            packaging="jar",
                            strict=True,
                        )
                    ]
                ),
                file_digest=FileDigest(
                    "52dc5551b0257666526c5095424567fed7dc7b00d2b1ba7bd52298411112b1d0", 482530
                ),
                remote_url=None,
                pants_address=None,
            ),
        )
    )


@maybe_skip_jdk_test
def test_resolve_with_broken_url(rule_runner: RuleRunner) -> None:

    coordinate = ArtifactRequirement(
        coordinate=Coordinate(
            group="org.hamcrest",
            artifact="hamcrest-core",
            version="1.3_inexplicably_wrong",  # if the group/artifact/version is real, coursier will fallback
        ),
        url="https://this_url_does_not_work",
    )

    expected_exception_msg = r".*this_url_does_not_work not found under https.*"

    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(
            CoursierResolvedLockfile,
            [ArtifactRequirements([coordinate])],
        )


@maybe_skip_jdk_test
def test_resolve_with_working_url(rule_runner: RuleRunner) -> None:

    requirement = ArtifactRequirement(
        coordinate=Coordinate(
            group="apache-commons-local",
            artifact="commons-collections",
            version="1.0.0_JAR_LOCAL",
        ),
        url="https://repo1.maven.org/maven2/org/apache/commons/commons-collections4/4.2/commons-collections4-4.2.jar",
    )

    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [ArtifactRequirements([requirement])],
    )

    coordinate = requirement.coordinate

    assert resolved_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=Coordinate(
                    group=coordinate.group, artifact=coordinate.artifact, version=coordinate.version
                ),
                file_name=f"{coordinate.group}_{coordinate.artifact}_{coordinate.version}.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="6a594721d51444fd97b3eaefc998a77f606dedb03def494f74755aead3c9df3e",
                    serialized_bytes_length=752798,
                ),
                remote_url=requirement.url,
                pants_address=None,
            ),
        )
    )


@maybe_skip_jdk_test
def test_resolve_with_a_jar(rule_runner: RuleRunner) -> None:

    rule_runner.write_files(
        {
            "BUILD": textwrap.dedent(
                """\
                jvm_artifact(
                  name="jeremy",
                  group="jeremy",
                  artifact="jeremy",
                  version="4.13.2",
                  jar="jeremy.jar",
                )
                """
            ),
            "jeremy.jar": "hello dave",
        }
    )

    targets = rule_runner.request(Targets, [AddressSpecs([DescendantAddresses("")])])
    jeremy_target = targets[0]

    jar_field = jeremy_target[JvmArtifactJarSourceField]

    requirement = ArtifactRequirement(
        coordinate=Coordinate(
            group="jeremy",
            artifact="jeremy",
            version="4.13.2",
        ),
        jar=jar_field,
    )

    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [ArtifactRequirements([requirement])],
    )

    coordinate = requirement.coordinate
    assert resolved_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=Coordinate(
                    group=coordinate.group, artifact=coordinate.artifact, version=coordinate.version
                ),
                file_name=f"{coordinate.group}_{coordinate.artifact}_{coordinate.version}.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="55b9afa8d7776cd6c318eec51f506e9c7f66c247dcec343d4667f5f269714f86",
                    serialized_bytes_length=10,
                ),
                pants_address=jar_field.address.spec,
            ),
        )
    )


@maybe_skip_jdk_test
def test_generate_lockfile(rule_runner: RuleRunner) -> None:
    """Test our `GenerateLockfile` rule, not just the resolving stage with Coursier.

    For example, test that we add metadata properly.
    """
    artifacts = ArtifactRequirements(
        [ArtifactRequirement(Coordinate("org.hamcrest", "hamcrest-core", "1.3"))]
    )
    result = rule_runner.request(
        GenerateLockfileResult,
        [GenerateJvmLockfile(artifacts=artifacts, resolve_name="test", lockfile_dest="lock.txt")],
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
    rule_runner.set_options(["--jvm-resolves={'a': 'a.lock', 'b': 'b.lock'}"], env_inherit={"PATH"})

    result = rule_runner.request(UserGenerateLockfiles, [RequestedJVMserResolveNames(["a", "b"])])
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
        ),
    }
