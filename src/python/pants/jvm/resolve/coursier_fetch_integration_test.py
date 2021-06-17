# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import FileDigest
from pants.engine.internals.scheduler import ExecutionError
from pants.jvm.resolve.coursier_fetch import (
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
    MavenCoord,
    MavenCoordinates,
    MavenRequirements,
    ResolvedClasspathEntry,
)
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.target_types import JvmDependencyLockfile
from pants.jvm.util_rules import ExtractFileDigest
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *util_rules(),
            QueryRule(CoursierResolvedLockfile, (MavenRequirements,)),
            QueryRule(ResolvedClasspathEntry, (CoursierLockfileEntry,)),
            QueryRule(FileDigest, (ExtractFileDigest,)),
        ],
        target_types=[JvmDependencyLockfile],
    )


def test_empty_resolve(rule_runner: RuleRunner) -> None:
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [
            MavenRequirements.create_from_maven_coordinates_fields(
                fields=(),
            )
        ],
    )
    assert resolved_lockfile == CoursierResolvedLockfile(entries=())


# TODO(#11928): Make all of these tests more hermetic and not dependent on having a network connection.


def test_resolve_with_no_deps(rule_runner: RuleRunner) -> None:
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [
            MavenRequirements.create_from_maven_coordinates_fields(
                fields=(),
                additional_requirements=["org.hamcrest:hamcrest-core:1.3"],
            )
        ],
    )
    assert resolved_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=MavenCoord(coord="org.hamcrest:hamcrest-core:1.3"),
                file_name="hamcrest-core-1.3.jar",
                direct_dependencies=MavenCoordinates([]),
                dependencies=MavenCoordinates([]),
                file_digest=FileDigest(
                    fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                    serialized_bytes_length=45024,
                ),
            ),
        )
    )


def test_resolve_with_transitive_deps(rule_runner: RuleRunner) -> None:
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [
            MavenRequirements.create_from_maven_coordinates_fields(
                fields=(),
                additional_requirements=["junit:junit:4.13.2"],
            )
        ],
    )

    assert resolved_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=MavenCoord(coord="junit:junit:4.13.2"),
                file_name="junit-4.13.2.jar",
                direct_dependencies=MavenCoordinates(
                    [MavenCoord(coord="org.hamcrest:hamcrest-core:1.3")]
                ),
                dependencies=MavenCoordinates([MavenCoord(coord="org.hamcrest:hamcrest-core:1.3")]),
                file_digest=FileDigest(
                    fingerprint="8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3",
                    serialized_bytes_length=384581,
                ),
            ),
            CoursierLockfileEntry(
                coord=MavenCoord(coord="org.hamcrest:hamcrest-core:1.3"),
                file_name="hamcrest-core-1.3.jar",
                direct_dependencies=MavenCoordinates([]),
                dependencies=MavenCoordinates([]),
                file_digest=FileDigest(
                    fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                    serialized_bytes_length=45024,
                ),
            ),
        )
    )


def test_resolve_with_inexact_coord(rule_runner: RuleRunner) -> None:
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [
            MavenRequirements.create_from_maven_coordinates_fields(
                fields=(),
                # Note the open-ended coordinate here.  We will still resolve this for the user, but the result
                # will be exact and pinned.  As noted above, this is an especially brittle unit test, but version
                # 4.8 was chosen because it has multiple patch versions and no new versions have been uploaded
                # to 4.8.x in over a decade.
                additional_requirements=["junit:junit:4.8+"],
            )
        ],
    )

    assert resolved_lockfile == CoursierResolvedLockfile(
        entries=(
            CoursierLockfileEntry(
                coord=MavenCoord(coord="junit:junit:4.8.2"),
                file_name="junit-4.8.2.jar",
                direct_dependencies=MavenCoordinates([]),
                dependencies=MavenCoordinates([]),
                file_digest=FileDigest(
                    fingerprint="a2aa2c3bb2b72da76c3e6a71531f1eefdc350494819baf2b1d80d7146e020f9e",
                    serialized_bytes_length=237344,
                ),
            ),
        )
    )


def test_fetch_one_coord_with_no_deps(rule_runner: RuleRunner) -> None:

    classpath_entry = rule_runner.request(
        ResolvedClasspathEntry,
        [
            CoursierLockfileEntry(
                coord=MavenCoord(coord="org.hamcrest:hamcrest-core:1.3"),
                file_name="hamcrest-core-1.3.jar",
                direct_dependencies=MavenCoordinates([]),
                dependencies=MavenCoordinates([]),
                file_digest=FileDigest(
                    fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
                    serialized_bytes_length=45024,
                ),
            )
        ],
    )
    assert classpath_entry.coord == MavenCoord(coord="org.hamcrest:hamcrest-core:1.3")
    assert classpath_entry.file_name == "hamcrest-core-1.3.jar"
    file_digest = rule_runner.request(
        FileDigest, [ExtractFileDigest(classpath_entry.digest, "hamcrest-core-1.3.jar")]
    )
    assert file_digest == FileDigest(
        fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
        serialized_bytes_length=45024,
    )


def test_fetch_one_coord_with_transitive_deps(rule_runner: RuleRunner) -> None:

    classpath_entry = rule_runner.request(
        ResolvedClasspathEntry,
        [
            CoursierLockfileEntry(
                coord=MavenCoord(coord="junit:junit:4.13.2"),
                file_name="junit-4.13.2.jar",
                direct_dependencies=MavenCoordinates(
                    [MavenCoord(coord="org.hamcrest:hamcrest-core:1.3")]
                ),
                dependencies=MavenCoordinates([MavenCoord(coord="org.hamcrest:hamcrest-core:1.3")]),
                file_digest=FileDigest(
                    fingerprint="8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3",
                    serialized_bytes_length=384581,
                ),
            )
        ],
    )
    assert classpath_entry.coord == MavenCoord(coord="junit:junit:4.13.2")
    assert classpath_entry.file_name == "junit-4.13.2.jar"
    file_digest = rule_runner.request(
        FileDigest, [ExtractFileDigest(classpath_entry.digest, "junit-4.13.2.jar")]
    )
    assert file_digest == FileDigest(
        fingerprint="8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3",
        serialized_bytes_length=384581,
    )


def test_fetch_one_coord_with_bad_fingerprint(rule_runner: RuleRunner) -> None:
    expected_exception_msg = (
        r".*?CoursierError:.*?Coursier fetch for .*?hamcrest.*? succeeded.*?"
        r"66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9.*?"
        r"did not match.*?ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    )
    lockfile_entry = CoursierLockfileEntry(
        coord=MavenCoord(coord="org.hamcrest:hamcrest-core:1.3"),
        file_name="hamcrest-core-1.3.jar",
        direct_dependencies=MavenCoordinates([]),
        dependencies=MavenCoordinates([]),
        file_digest=FileDigest(
            fingerprint="ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
            serialized_bytes_length=45024,
        ),
    )
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(ResolvedClasspathEntry, [lockfile_entry])


def test_fetch_one_coord_with_bad_length(rule_runner: RuleRunner) -> None:
    expected_exception_msg = (
        r".*?CoursierError:.*?Coursier fetch for .*?hamcrest.*? succeeded.*?"
        r"66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9.*?"
        r"serialized_bytes_length=45024.*?"
        r"did not match.*?66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9.*?"
        r"serialized_bytes_length=1\).*?"
    )
    lockfile_entry = CoursierLockfileEntry(
        coord=MavenCoord(coord="org.hamcrest:hamcrest-core:1.3"),
        file_name="hamcrest-core-1.3.jar",
        direct_dependencies=MavenCoordinates([]),
        dependencies=MavenCoordinates([]),
        file_digest=FileDigest(
            fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
            serialized_bytes_length=1,
        ),
    )
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(ResolvedClasspathEntry, [lockfile_entry])


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
        coord=MavenCoord(coord="org.hamcrest:hamcrest-core:1.3+"),
        file_name="hamcrest-core-1.3.jar",
        direct_dependencies=MavenCoordinates([]),
        dependencies=MavenCoordinates([]),
        file_digest=FileDigest(
            fingerprint="66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9",
            serialized_bytes_length=45024,
        ),
    )
    with pytest.raises(ExecutionError, match=expected_exception_msg):
        rule_runner.request(ResolvedClasspathEntry, [lockfile_entry])
