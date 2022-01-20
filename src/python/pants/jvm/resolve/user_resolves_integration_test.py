# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap

import pytest

from pants.core.util_rules import config_files, source_files
from pants.engine.fs import FileDigest
from pants.engine.internals.scheduler import ExecutionError
from pants.jvm.compile import ClasspathEntry
from pants.jvm.goals import lockfile
from pants.jvm.resolve.common import (
    ArtifactRequirements,
    Coordinate,
    Coordinates,
    CoursierLockfileEntry,
    CoursierResolvedLockfile,
)
from pants.jvm.resolve.user_resolves import rules as coursier_fetch_rules
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import ExtractFileDigest
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner

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
            *source_files.rules(),
            *util_rules(),
            *lockfile.rules(),
            QueryRule(CoursierResolvedLockfile, (ArtifactRequirements,)),
            QueryRule(ClasspathEntry, (CoursierLockfileEntry,)),
            QueryRule(FileDigest, (ExtractFileDigest,)),
        ],
        target_types=[JvmArtifactTarget],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_fetch_one_coord_with_jar(rule_runner: RuleRunner) -> None:
    coord = Coordinate(group="jeremy", artifact="jeremy", version="4.13.2")
    file_name = f"{coord.group}_{coord.artifact}_{coord.version}.jar"
    rule_runner.write_files(
        {
            "BUILD": textwrap.dedent(
                f"""\
            jvm_artifact(
              name="jeremy",
              group="{coord.group}",
              artifact="{coord.artifact}",
              version="{coord.version}",
              jar="jeremy.jar",
            )
            """
            ),
            "jeremy.jar": "hello dave",
        }
    )

    classpath_entry = rule_runner.request(
        ClasspathEntry,
        [
            CoursierLockfileEntry(
                coord=coord,
                file_name=file_name,
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="55b9afa8d7776cd6c318eec51f506e9c7f66c247dcec343d4667f5f269714f86",
                    serialized_bytes_length=10,
                ),
                pants_address="//:jeremy",
            )
        ],
    )
    assert classpath_entry.filenames == (file_name,)
    file_digest = rule_runner.request(
        FileDigest,
        [ExtractFileDigest(classpath_entry.digest, file_name)],
    )
    assert file_digest == FileDigest(
        fingerprint="55b9afa8d7776cd6c318eec51f506e9c7f66c247dcec343d4667f5f269714f86",
        serialized_bytes_length=10,
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
def test_fetch_one_coord_with_classifier(rule_runner: RuleRunner) -> None:
    # Has as a transitive dependency an artifact with both a `classifier` and `packaging`.
    coordinate = Coordinate(group="org.apache.avro", artifact="avro-tools", version="1.11.0")
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [ArtifactRequirements.from_coordinates([coordinate])],
    )

    entries = [
        e
        for e in resolved_lockfile.entries
        if e.coord
        == Coordinate(
            group="org.apache.avro",
            artifact="trevni-avro",
            version="1.11.0",
            packaging="jar",
            classifier="tests",
            strict=True,
        )
    ]
    assert len(entries) == 1
    entry = entries[0]

    classpath_entry = rule_runner.request(ClasspathEntry, [entry])
    assert classpath_entry.filenames == ("org.apache.avro_trevni-avro_jar_tests_1.11.0.jar",)


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
