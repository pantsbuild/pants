# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import FileDigest
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import ProcessExecutionFailure
from pants.jvm.compile import ClasspathEntry
from pants.jvm.resolve.coursier_fetch import (
    ArtifactRequirement,
    ArtifactRequirements,
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmArtifact
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import ExtractFileDigest
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner, engine_error

HAMCREST_COORD = Coordinate(
    group="org.hamcrest",
    artifact="hamcrest-core",
    version="1.3",
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *util_rules(),
            QueryRule(CoursierResolvedLockfile, (ArtifactRequirements,)),
            QueryRule(ClasspathEntry, (CoursierLockfileEntry,)),
            QueryRule(FileDigest, (ExtractFileDigest,)),
        ],
        target_types=[JvmArtifact],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


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
        url="https://search.maven.org/remotecontent?filepath=org/apache/commons/commons-collections4/4.2/commons-collections4-4.2.jar",
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
            ),
        )
    )


@maybe_skip_jdk_test
def test_fetch_one_coord_with_no_deps(rule_runner: RuleRunner) -> None:

    classpath_entry = rule_runner.request(
        ClasspathEntry,
        [
            CoursierLockfileEntry(
                coord=HAMCREST_COORD,
                file_name="org.hamcrest_hamcrest-core_1.3.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                    serialized_bytes_length=45024,
                ),
            )
        ],
    )
    assert classpath_entry.filenames == ("org.hamcrest_hamcrest-core_1.3.jar",)
    file_digest = rule_runner.request(
        FileDigest,
        [ExtractFileDigest(classpath_entry.digest, "org.hamcrest_hamcrest-core_1.3.jar")],
    )
    assert file_digest == FileDigest(
        fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
        serialized_bytes_length=45024,
    )


@maybe_skip_jdk_test
def test_fetch_one_coord_with_transitive_deps(rule_runner: RuleRunner) -> None:
    junit_coord = Coordinate(group="junit", artifact="junit", version="4.13.2")
    classpath_entry = rule_runner.request(
        ClasspathEntry,
        [
            CoursierLockfileEntry(
                coord=junit_coord,
                file_name="junit_junit_4.13.2.jar",
                direct_dependencies=Coordinates([HAMCREST_COORD]),
                dependencies=Coordinates([HAMCREST_COORD]),
                file_digest=FileDigest(
                    fingerprint="8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3",
                    serialized_bytes_length=384581,
                ),
            )
        ],
    )
    assert classpath_entry.filenames == ("junit_junit_4.13.2.jar",)
    file_digest = rule_runner.request(
        FileDigest, [ExtractFileDigest(classpath_entry.digest, "junit_junit_4.13.2.jar")]
    )
    assert file_digest == FileDigest(
        fingerprint="8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3",
        serialized_bytes_length=384581,
    )


@maybe_skip_jdk_test
def test_fetch_one_coord_with_bad_fingerprint(rule_runner: RuleRunner) -> None:
    expected_exception_msg = (
        r".*?CoursierError:.*?Coursier fetch for .*?hamcrest.*? succeeded.*?"
        r"66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9.*?"
        r"did not match.*?ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    lockfile_entry = CoursierLockfileEntry(
        coord=HAMCREST_COORD,
        file_name="hamcrest-core-1.3.jar",
        direct_dependencies=Coordinates([]),
        dependencies=Coordinates([]),
        file_digest=FileDigest(
            fingerprint="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            serialized_bytes_length=45024,
        ),
    )
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(ClasspathEntry, [lockfile_entry])


@maybe_skip_jdk_test
def test_fetch_one_coord_with_bad_length(rule_runner: RuleRunner) -> None:
    expected_exception_msg = (
        r".*?CoursierError:.*?Coursier fetch for .*?hamcrest.*? succeeded.*?"
        r"66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9.*?"
        r", 45024.*?"
        r"did not match.*?66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9.*?"
        r", 1\).*?"
    )
    lockfile_entry = CoursierLockfileEntry(
        coord=HAMCREST_COORD,
        file_name="hamcrest-core-1.3.jar",
        direct_dependencies=Coordinates([]),
        dependencies=Coordinates([]),
        file_digest=FileDigest(
            fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
            serialized_bytes_length=1,
        ),
    )
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(ClasspathEntry, [lockfile_entry])


@maybe_skip_jdk_test
def test_fetch_one_coord_with_mismatched_coord(rule_runner: RuleRunner) -> None:
    """This test demonstrates that fetch_one_coord is picky about inexact coordinates.

    Even though the expected jar was downloaded, the coordinate in the lockfile entry was inexact, meaning
    it wasn't an exact string match for the coordinate fetched and reported by Coursier, which is exact.

    This shouldn't happen in practice, because these lockfile entries are ultimately derived from Coursier
    reports which always give exact coordinate strings.
    """
    expected_exception_msg = (
        r'Coursier resolved coord.*?"org.hamcrest:hamcrest-core:1.3".*?'
        r'does not match requested coord.*?"org.hamcrest:hamcrest-core:1.3\+".*?'
    )
    lockfile_entry = CoursierLockfileEntry(
        coord=Coordinate(group="org.hamcrest", artifact="hamcrest-core", version="1.3+"),
        file_name="hamcrest-core-1.3.jar",
        direct_dependencies=Coordinates([]),
        dependencies=Coordinates([]),
        file_digest=FileDigest(
            fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
            serialized_bytes_length=45024,
        ),
    )
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(ClasspathEntry, [lockfile_entry])
