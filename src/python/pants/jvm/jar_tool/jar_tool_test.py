# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import rules as target_types_rules
from pants.core.util_rules import archive, system_binaries
from pants.core.util_rules.archive import ExtractedArchive, MaybeExtractArchiveRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    Snapshot,
)
from pants.jvm import compile as jvm_compile
from pants.jvm import jdk_rules, non_jvm_dependencies
from pants.jvm.classpath import rules as classpath_rules
from pants.jvm.jar_tool import jar_tool
from pants.jvm.jar_tool.jar_tool import JarToolRequest
from pants.jvm.resolve import coursier_fetch, coursier_setup, jvm_tool
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
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_generate_jar_with_manifest(rule_runner: RuleRunner) -> None:
    jar_digest = rule_runner.request(
        Digest,
        [
            JarToolRequest(
                jar_name="test.jar",
                digest=EMPTY_DIGEST,
                main_class="com.example.Main",
                classpath_entries=["lib1.jar", "lib2.jar"],
            )
        ],
    )

    jar_extracted = rule_runner.request(
        ExtractedArchive, [MaybeExtractArchiveRequest(digest=jar_digest, use_suffix=".zip")]
    )
    jar_contents = rule_runner.request(DigestContents, [jar_extracted.digest])
    assert len(jar_contents) == 1
    assert jar_contents[0].path == "META-INF/MANIFEST.MF"

    jar_manifest = jar_contents[0].content.decode("utf-8")
    assert "Main-Class: com.example.Main" in jar_manifest
    assert "Class-Path: lib1.jar lib2.jar" in jar_manifest


@maybe_skip_jdk_test
def test_pack_files_into_jar(rule_runner: RuleRunner) -> None:
    file_to_add = FileContent("file.txt", content=b"Sample content")
    file_digest = rule_runner.request(Digest, [CreateDigest([file_to_add])])

    file_jar_location = "newpath/file.txt"
    jar_digest = rule_runner.request(
        Digest,
        [
            JarToolRequest(
                jar_name="test.jar",
                digest=file_digest,
                file_mappings={file_to_add.path: file_jar_location},
            )
        ],
    )

    jar_extracted = rule_runner.request(
        ExtractedArchive, [MaybeExtractArchiveRequest(digest=jar_digest, use_suffix=".zip")]
    )
    jar_snapshot = rule_runner.request(Snapshot, [jar_extracted.digest])
    assert len(jar_snapshot.files) == 2
    assert file_jar_location in jar_snapshot.files
