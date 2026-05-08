# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import rules as target_types_rules
from pants.core.util_rules import archive, system_binaries
from pants.core.util_rules.archive import ExtractedArchive, MaybeExtractArchiveRequest
from pants.engine.fs import Digest, Snapshot
from pants.jvm import compile as jvm_compile
from pants.jvm import jdk_rules, non_jvm_dependencies
from pants.jvm.classpath import rules as classpath_rules
from pants.jvm.compile import ClasspathEntry
from pants.jvm.jar_tool import jar_tool
from pants.jvm.jar_tool.jar_tool import JarToolRequest
from pants.jvm.resolve import coursier_fetch, coursier_setup, jvm_tool
from pants.jvm.resolve.common import ArtifactRequirement, ArtifactRequirements
from pants.jvm.resolve.coordinate import Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *system_binaries.rules(),
            *archive.rules(),
            *coursier_setup.rules(),
            *coursier_fetch.rules(),
            *classpath_rules(),
            *jvm_tool.rules(),
            *jar_tool.rules(),
            *jvm_compile.rules(),
            *non_jvm_dependencies.rules(),
            *jdk_rules.rules(),
            *java_dep_inf_rules(),
            *util_rules(),
            *target_types_rules(),
            QueryRule(Digest, (JarToolRequest,)),
            QueryRule(ExtractedArchive, (MaybeExtractArchiveRequest,)),
            QueryRule(CoursierResolvedLockfile, (ArtifactRequirements,)),
            QueryRule(ClasspathEntry, (CoursierLockfileEntry,)),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_repack_exact_iceberg_runtime_jar(rule_runner: RuleRunner) -> None:
    requirement = ArtifactRequirement(
        coordinate=Coordinate(
            group="org.apache.iceberg",
            artifact="iceberg-spark-runtime-4.0_2.13",
            version="1.10.1",
        ),
        url="https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-4.0_2.13/1.10.1/iceberg-spark-runtime-4.0_2.13-1.10.1.jar",
    )
    resolved_lockfile = rule_runner.request(
        CoursierResolvedLockfile,
        [ArtifactRequirements([requirement])],
    )
    assert resolved_lockfile.entries
    entry = resolved_lockfile.entries[0]

    classpath_entry = rule_runner.request(
        ClasspathEntry,
        [
            CoursierLockfileEntry(
                coord=entry.coord,
                file_name=entry.file_name,
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=entry.file_digest,
                remote_url=requirement.url,
            )
        ],
    )
    assert classpath_entry.filenames == (entry.file_name,)

    jar_digest = rule_runner.request(
        Digest,
        [
            JarToolRequest(
                jar_name="output.jar",
                digest=classpath_entry.digest,
                jars=[entry.file_name],
                compress=True,
                policies=[("^LICENSE", "replace")],
            )
        ],
    )

    jar_extracted = rule_runner.request(
        ExtractedArchive, [MaybeExtractArchiveRequest(digest=jar_digest, use_suffix=".zip")]
    )
    jar_snapshot = rule_runner.request(Snapshot, [jar_extracted.digest])
    assert "org/apache/iceberg/spark/SparkCatalog.class" in jar_snapshot.files
    assert "LICENSE" in jar_snapshot.files
