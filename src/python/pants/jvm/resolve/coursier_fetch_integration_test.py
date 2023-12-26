# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import textwrap

import pytest

from pants.base.specs import RawSpecs, RecursiveGlobSpec
from pants.core.util_rules import config_files, source_files
from pants.engine.fs import FileDigest
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.process import ProcessExecutionFailure
from pants.engine.target import Targets
from pants.jvm.compile import ClasspathEntry
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements
from pants.jvm.resolve.coordinate import Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.target_types import JvmArtifactJarSourceField, JvmArtifactTarget
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
            *source_files.rules(),
            *util_rules(),
            QueryRule(Targets, [RawSpecs]),
            QueryRule(CoursierResolvedLockfile, (ArtifactRequirements,)),
            QueryRule(ClasspathEntry, (CoursierLockfileEntry,)),
            QueryRule(FileDigest, (ExtractFileDigest,)),
        ],
        target_types=[JvmArtifactTarget],
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


@pytest.mark.skip(reason="TODO(#15824)")
@pytest.mark.no_error_if_skipped
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
        Coordinate(
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
        Coordinate(
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

    targets = rule_runner.request(
        Targets, [RawSpecs(recursive_globs=(RecursiveGlobSpec(""),), description_of_origin="tests")]
    )
    jeremy_target = targets[0]

    jar_field = jeremy_target[JvmArtifactJarSourceField]

    requirement = ArtifactRequirement(
        Coordinate(
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


@maybe_skip_jdk_test
def test_fetch_one_coord_with_non_jar_packaging(rule_runner: RuleRunner) -> None:
    """This test demonstrates that fetch_one_coord is able to download non-jar artifacts such as
    protoc plugin binaries that are distributed via Maven Central."""
    coordinate = Coordinate(
        group="io.grpc",
        artifact="protoc-gen-grpc-java",
        version="1.48.0",
        packaging="exe",
        classifier="linux-x86_64",
    )
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [ArtifactRequirements.from_coordinates([coordinate])],
    )

    entries = [
        e
        for e in resolved_lockfile.entries
        if e.coord
        == Coordinate(
            group="io.grpc",
            artifact="protoc-gen-grpc-java",
            version="1.48.0",
            packaging="exe",
            classifier="linux-x86_64",
            strict=True,
        )
    ]
    assert len(entries) == 1
    entry = entries[0]

    classpath_entry = rule_runner.request(ClasspathEntry, [entry])
    assert classpath_entry.filenames == (
        "io.grpc_protoc-gen-grpc-java_exe_linux-x86_64_1.48.0.exe",
    )


@maybe_skip_jdk_test
def test_user_repo_order_is_respected(rule_runner: RuleRunner) -> None:
    """Tests that the repo resolution order issue found in #14577 is avoided."""

    jai_core = Coordinate(group="javax.media", artifact="jai_core", version="1.1.3")

    # `repo1.maven.org` has a bogus POM that Coursier hits first
    # `repo.osgeo.org` has a valid POM and should succeed
    rule_runner.set_options(
        args=[
            """--coursier-repos=['https://repo1.maven.org/maven2', 'https://repo.osgeo.org/repository/release']"""
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    with engine_error(ProcessExecutionFailure):
        rule_runner.request(
            CoursierResolvedLockfile,
            [
                ArtifactRequirements.from_coordinates([jai_core]),
            ],
        )

    rule_runner.set_options(
        args=[
            """--coursier-repos=['https://repo.osgeo.org/repository/release', 'https://repo1.maven.org/maven2']"""
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    rule_runner.request(
        CoursierResolvedLockfile,
        [
            ArtifactRequirements.from_coordinates([jai_core]),
        ],
    )


@maybe_skip_jdk_test
def test_transitive_excludes(rule_runner: RuleRunner) -> None:
    resolve = rule_runner.request(
        CoursierResolvedLockfile,
        [
            ArtifactRequirements(
                [
                    ArtifactRequirement(
                        coordinate=Coordinate(
                            group="com.fasterxml.jackson.core",
                            artifact="jackson-databind",
                            version="2.12.1",
                        )
                    ).with_extra_excludes("com.fasterxml.jackson.core:jackson-core")
                ]
            ),
        ],
    )

    entries = resolve.entries
    assert any(i for i in entries if i.coord.artifact == "jackson-databind")
    assert not any(i for i in entries if i.coord.artifact == "jackson-core")


@maybe_skip_jdk_test
def test_missing_entry_for_transitive_dependency(rule_runner: RuleRunner) -> None:
    resolve = rule_runner.request(
        CoursierResolvedLockfile,
        [
            ArtifactRequirements(
                [
                    ArtifactRequirement(
                        coordinate=Coordinate(
                            group="org.apache.hive",
                            artifact="hive-exec",
                            version="1.1.0",
                        )
                    ).with_extra_excludes(
                        "org.apache.calcite:calcite-avatica",
                        "org.apache.calcite:calcite-core",
                        "jdk.tools:jdk.tools",
                    )
                ]
            )
        ],
    )

    coords_of_entries = {(entry.coord.group, entry.coord.artifact) for entry in resolve.entries}
    coords_of_dependencies = {
        (d.group, d.artifact) for entry in resolve.entries for d in entry.dependencies
    }
    missing = coords_of_dependencies - coords_of_entries

    # We expect all the dependencies to have an entry, but right now it's not true
    # for ("junit", "junit") and ("org.apache.curator", "apache-curator").
    # TODO Remove the workaround once the bug is fixed.
    assert missing == {("junit", "junit"), ("org.apache.curator", "apache-curator")}


@maybe_skip_jdk_test
def test_failed_to_fetch_jar_given_packaging_pom(rule_runner: RuleRunner) -> None:
    reqs = ArtifactRequirements(
        [
            ArtifactRequirement(
                coordinate=Coordinate(
                    group="org.apache.curator",
                    artifact="apache-curator",
                    version="5.5.0",
                )
            )
        ]
    )

    # TODO Remove the workaround once the bug is fixed.
    with pytest.raises(
        Exception,
        match=r"Exception: No jar found for org.apache.curator:apache-curator:5.5.0. .*",
    ):
        rule_runner.request(CoursierResolvedLockfile, [reqs])


@maybe_skip_jdk_test
def test_force_version(rule_runner):
    # first check that force_version=False leads to a different version
    reqs = ArtifactRequirements(
        [
            ArtifactRequirement(
                coordinate=Coordinate(
                    group="org.apache.parquet",
                    artifact="parquet-common",
                    version="1.13.1",
                )
            ),
            Coordinate(
                group="org.slf4j",
                artifact="slf4j-api",
                version="1.7.19",
            ).as_requirement(),
        ]
    )
    reqs = ArtifactRequirements(
        [
            Coordinate(
                group="org.apache.parquet",
                artifact="parquet-common",
                version="1.13.1",
            ).as_requirement(),
            ArtifactRequirement(
                coordinate=Coordinate(
                    group="org.slf4j",
                    artifact="slf4j-api",
                    version="1.7.19",
                )
            ),
        ]
    )
    entries = rule_runner.request(CoursierResolvedLockfile, [reqs]).entries
    assert Coordinate(
        group="org.slf4j",
        artifact="slf4j-api",
        version="1.7.22",
    ) in [e.coord for e in entries]

    # then check force_version=True pins the version
    reqs = ArtifactRequirements(
        [
            ArtifactRequirement(
                coordinate=Coordinate(
                    group="org.apache.parquet",
                    artifact="parquet-common",
                    version="1.13.1",
                )
            ),
            dataclasses.replace(
                Coordinate(
                    group="org.slf4j",
                    artifact="slf4j-api",
                    version="1.7.19",
                ).as_requirement(),
                force_version=True,
            ),
        ]
    )
    reqs = ArtifactRequirements(
        [
            Coordinate(
                group="org.apache.parquet",
                artifact="parquet-common",
                version="1.13.1",
            ).as_requirement(),
            dataclasses.replace(
                ArtifactRequirement(
                    coordinate=Coordinate(
                        group="org.slf4j",
                        artifact="slf4j-api",
                        version="1.7.19",
                    )
                ),
                force_version=True,
            ),
        ]
    )
    entries = rule_runner.request(CoursierResolvedLockfile, [reqs]).entries
    assert Coordinate(
        group="org.slf4j",
        artifact="slf4j-api",
        version="1.7.19",
        strict=True,
    ) in [e.coord for e in entries]
