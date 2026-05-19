# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.java.target_types import JavaSourcesGeneratorTarget
from pants.backend.java.target_types import rules as target_types_rules
from pants.core.util_rules import config_files, source_files
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import EMPTY_DIGEST
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.resolve.coursier_fetch import CoursierResolvedLockfile, NoCompatibleResolve
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.resolve.lockfile_metadata import JVMLockfileMetadata
from pants.jvm.target_types import DeployJarTarget, JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner, engine_error

NAMED_RESOLVE_OPTIONS = (
    '--jvm-resolves={"one": "coursier_resolve.lockfile", "two": "coursier_resolve.lockfile"}'
)
DEFAULT_RESOLVE_OPTION = "--jvm-default-resolve=one"


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *source_files.rules(),
            *util_rules(),
            *target_types_rules(),
            QueryRule(CoursierResolveKey, (Addresses,)),
        ],
        target_types=[DeployJarTarget, JavaSourcesGeneratorTarget, JvmArtifactTarget],
    )
    rule_runner.set_options(
        args=[
            NAMED_RESOLVE_OPTIONS,
            DEFAULT_RESOLVE_OPTION,
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


def assert_resolve(
    expected_resolve: str,
    rule_runner: RuleRunner,
    root_one_resolve: str,
    root_two_resolve: str,
    leaf_resolve: str,
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""\
                deploy_jar(name='root_one', main='Ex', dependencies=[':leaf'], resolve='{root_one_resolve}')
                deploy_jar(name='root_two', main='Ex', dependencies=[':leaf'], resolve='{root_two_resolve}')
                jvm_artifact(
                  name='leaf',
                  group='ex',
                  artifact='ex',
                  version='0.0.0',
                  resolve='{leaf_resolve}',
                )
                """
            ),
            "coursier_resolve.lockfile": "[]",
        }
    )
    resolve_key = rule_runner.request(
        CoursierResolveKey,
        # NB: Although it will not happen for `deploy_jars` in production, we resolve two of them
        # together here to validate the handling of multiple roots, which _can_ happen for things
        # like the `repl` goal, and other goals which create an adhoc merged Classpath.
        [
            Addresses(
                [
                    Address(spec_path="", target_name="root_one"),
                    Address(spec_path="", target_name="root_two"),
                ]
            )
        ],
    )
    assert resolve_key.name == expected_resolve


@maybe_skip_jdk_test
def test_all_matching(rule_runner: RuleRunner) -> None:
    assert_resolve("one", rule_runner, "one", "one", "one")


@maybe_skip_jdk_test
def test_no_matching_for_root(rule_runner: RuleRunner) -> None:
    with engine_error(NoCompatibleResolve):
        assert_resolve("n/a", rule_runner, "one", "two", "two")


@maybe_skip_jdk_test
def test_no_matching_for_leaf(rule_runner: RuleRunner) -> None:
    with engine_error(NoCompatibleResolve):
        assert_resolve("n/a", rule_runner, "one", "one", "two")


@pytest.mark.parametrize(
    "coord_str,expected",
    (
        ("group:artifact:version", Coordinate("group", "artifact", "version")),
        (
            "group:artifact:packaging:version",
            Coordinate("group", "artifact", "version", "packaging"),
        ),
        (
            "group:artifact:packaging:classifier:version",
            Coordinate("group", "artifact", "version", "packaging", "classifier"),
        ),
    ),
)
def test_from_coord_str(coord_str: str, expected: Coordinate) -> None:
    assert Coordinate.from_coord_str(coord_str) == expected


def test_dependencies_skips_transitive_entries_missing_from_lockfile() -> None:
    # Regression test for the v2.31 KeyError that surfaced after #22906 removed the
    # `entries.get(...)` guard. Coursier (still as of 2.1.25-M19) sometimes emits
    # transitive dependencies that have no top-level coord entry of their own — see
    # https://github.com/coursier/coursier/issues/2884 — so `dependencies()` must
    # tolerate the missing entry rather than raising KeyError. This fixture is the
    # one from the original bug report: hive-exec lists arrow-memory as a transitive
    # dependency, but no arrow-memory entry exists.
    metadata = JVMLockfileMetadata.new([])
    lockfile = CoursierResolvedLockfile.from_serialized(
        metadata.add_header_to_lockfile(
            dedent(
                """\
                [[entries]]
                file_name = "org.apache.hive_hive-exec_3.1.3.jar"

                [[entries.directDependencies]]
                group = "commons-codec"
                artifact = "commons-codec"
                version = "1.17.0"
                packaging = "jar"

                [[entries.dependencies]]
                group = "commons-codec"
                artifact = "commons-codec"
                version = "1.17.0"
                packaging = "jar"

                [[entries.dependencies]]
                group = "org.apache.arrow"
                artifact = "arrow-memory"
                version = "0.8.0"
                packaging = "jar"

                [entries.coord]
                group = "org.apache.hive"
                artifact = "hive-exec"
                version = "3.1.3"
                packaging = "jar"

                [entries.file_digest]
                fingerprint = "a39058a6028ad36a74f97639663c94d9d4c52d9d32fab31032270565d01424af"
                serialized_bytes_length = 492916

                [[entries]]
                directDependencies = []
                dependencies = []
                file_name = "commons-codec_commons-codec_1.17.0.jar"

                [entries.coord]
                group = "commons-codec"
                artifact = "commons-codec"
                version = "1.17.0"
                packaging = "jar"

                [entries.file_digest]
                fingerprint = "0000000000000000000000000000000000000000000000000000000000000000"
                serialized_bytes_length = 1
                """
            ).encode(),
            regenerate_command="N/A - regression fixture",
            delimeter="#",
        )
    )

    root_entry, transitive_entries = lockfile.dependencies(
        CoursierResolveKey(
            name="forge-jvm-spark-3-5",
            path="lockfiles/jvm-spark-3-5.lock",
            digest=EMPTY_DIGEST,
        ),
        Coordinate(group="org.apache.hive", artifact="hive-exec", version="3.1.3"),
    )

    assert root_entry.coord == Coordinate(
        group="org.apache.hive",
        artifact="hive-exec",
        version="3.1.3",
        strict=True,
    )
    # arrow-memory has no entry of its own, so it is silently skipped here.
    assert {(entry.coord.group, entry.coord.artifact) for entry in transitive_entries} == {
        ("commons-codec", "commons-codec"),
    }
    # ...but it still appears in the raw dependency list of hive-exec.
    assert {(dep.group, dep.artifact) for dep in root_entry.dependencies} == {
        ("commons-codec", "commons-codec"),
        ("org.apache.arrow", "arrow-memory"),
    }
