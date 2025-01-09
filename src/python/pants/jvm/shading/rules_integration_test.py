# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import rules as target_types_rules
from pants.core.util_rules import archive
from pants.core.util_rules.archive import ExtractedArchive, MaybeExtractArchiveRequest
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, Snapshot
from pants.engine.target import AllTargets, CoarsenedTargets, CoarsenedTargetsRequest
from pants.jvm import classpath
from pants.jvm import compile as jvm_compile
from pants.jvm import jdk_rules, non_jvm_dependencies
from pants.jvm.compile import ClasspathEntry
from pants.jvm.resolve import coursier_fetch, coursier_setup, jvm_tool
from pants.jvm.resolve.coordinate import Coordinate
from pants.jvm.resolve.coursier_fetch import CoursierFetchRequest
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.shading.rules import ShadedJar, ShadeJarRequest
from pants.jvm.shading.rules import rules as shading_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import (
    JvmArtifactFieldSet,
    JvmArtifactTarget,
    JvmShadingRelocateRule,
    JvmShadingRenameRule,
)
from pants.jvm.testutil import _get_jar_contents_snapshot, maybe_skip_jdk_test
from pants.jvm.util_rules import rules as jvm_util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[JvmArtifactTarget],
        rules=[
            *shading_rules(),
            *archive.rules(),
            *coursier_setup.rules(),
            *coursier_fetch.rules(),
            *classpath.rules(),
            *jdk_rules.rules(),
            *non_jvm_dependencies.rules(),
            *jvm_tool.rules(),
            *jvm_util_rules(),
            *jvm_compile.rules(),
            *java_dep_inf_rules(),
            *strip_jar.rules(),
            *target_types_rules(),
            QueryRule(ShadedJar, (ShadeJarRequest,)),
            QueryRule(AllTargets, ()),
            QueryRule(CoarsenedTargets, (CoarsenedTargetsRequest,)),
            QueryRule(CoursierResolveKey, (CoarsenedTargets,)),
            QueryRule(ClasspathEntry, (CoursierFetchRequest,)),
            QueryRule(ExtractedArchive, (MaybeExtractArchiveRequest,)),
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


_TEST_COMMONS_LANG_COORD = "commons-lang:commons-lang:2.6"


@pytest.fixture
def jarjar_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "jarjar.test.lock", ["com.eed3si9n.jarjar:jarjar-assembly:1.8.1", _TEST_COMMONS_LANG_COORD]
    )


@pytest.fixture
def jarjar_lockfile(
    jarjar_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return jarjar_lockfile_def.load(request)


def _resolve_jar(rule_runner: RuleRunner, coord: Coordinate) -> ClasspathEntry:
    jvm_artifact_field_sets = [
        JvmArtifactFieldSet.create(tgt)
        for tgt in rule_runner.request(AllTargets, [])
        if JvmArtifactFieldSet.is_applicable(tgt)
    ]
    coarsened_tgts = rule_runner.request(
        CoarsenedTargets,
        [
            CoarsenedTargetsRequest(
                [
                    fs.address
                    for fs in jvm_artifact_field_sets
                    if fs.artifact.value == coord.artifact
                    and fs.group.value == coord.group
                    and fs.version.value == coord.version
                ]
            )
        ],
    )
    assert len(coarsened_tgts) == 1

    resolve_key = rule_runner.request(CoursierResolveKey, [coarsened_tgts])
    return rule_runner.request(
        ClasspathEntry, [CoursierFetchRequest(coarsened_tgts[0], resolve=resolve_key)]
    )


@maybe_skip_jdk_test
def test_shade_commons_lang(rule_runner: RuleRunner, jarjar_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": jarjar_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": jarjar_lockfile.requirements_as_jvm_artifact_targets(),
        }
    )

    commons_lang_classpath = _resolve_jar(
        rule_runner, Coordinate.from_coord_str(_TEST_COMMONS_LANG_COORD)
    )
    shaded_jar = rule_runner.request(
        ShadedJar,
        [
            ShadeJarRequest(
                path=commons_lang_classpath.filenames[0],
                digest=commons_lang_classpath.digest,
                rules=[
                    JvmShadingRelocateRule(
                        package="org.apache.commons.lang", into="legacy.commons_lang"
                    )
                ],
            )
        ],
    )

    assert shaded_jar.path
    assert shaded_jar.digest != EMPTY_DIGEST

    jar_contents = _get_jar_contents_snapshot(
        rule_runner, filename=shaded_jar.path, digest=shaded_jar.digest
    )
    non_meta_dir_names = [
        dirname
        for dirname in jar_contents.dirs
        if not dirname.startswith("META-INF") and dirname != "legacy"
    ]
    count_renamed_dirs = sum(
        [1 for dirname in non_meta_dir_names if dirname.startswith("legacy/commons_lang")]
    )

    assert count_renamed_dirs == len(non_meta_dir_names)


@maybe_skip_jdk_test
def test_restore_input_path(rule_runner: RuleRunner, jarjar_lockfile: JVMLockfileFixture) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": jarjar_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": jarjar_lockfile.requirements_as_jvm_artifact_targets(),
        }
    )

    test_classpath_prefix = "__test"
    commons_lang_classpath = _resolve_jar(
        rule_runner, Coordinate.from_coord_str(_TEST_COMMONS_LANG_COORD)
    )

    input_digest = rule_runner.request(
        Digest, [AddPrefix(commons_lang_classpath.digest, test_classpath_prefix)]
    )
    input_path = os.path.join(test_classpath_prefix, commons_lang_classpath.filenames[0])
    shaded_jar = rule_runner.request(
        ShadedJar,
        [
            ShadeJarRequest(
                path=input_path,
                digest=input_digest,
                rules=[
                    JvmShadingRenameRule(
                        pattern="org.apache.commons.lang.**", replacement="legacy.commons_lang.@1"
                    )
                ],
            )
        ],
    )

    assert shaded_jar.path == input_path

    result_snapshot = rule_runner.request(Snapshot, [shaded_jar.digest])
    assert input_path in result_snapshot.files
