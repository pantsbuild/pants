# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.kotlin.compile.kotlinc import CompileKotlinSourceRequest
from pants.backend.kotlin.compile.kotlinc import rules as kotlinc_rules
from pants.backend.kotlin.goals.check import KotlincCheckRequest
from pants.backend.kotlin.goals.check import rules as kotlin_check_rules
from pants.backend.kotlin.target_types import KotlinSourcesGeneratorTarget
from pants.backend.kotlin.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResults
from pants.core.util_rules import config_files, source_files, system_binaries
from pants.engine.addresses import Addresses
from pants.engine.fs import FileDigest
from pants.engine.target import CoarsenedTargets
from pants.jvm import jdk_rules, testutil
from pants.jvm.compile import ClasspathEntry, CompileResult, FallibleClasspathEntry
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.common import ArtifactRequirement, Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.coursier_test_util import TestCoursierWrapper
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
    maybe_skip_jdk_test,
)
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *config_files.rules(),
            *jvm_tool.rules(),
            *system_binaries.rules(),
            *jdk_rules.rules(),
            *kotlin_check_rules(),
            *kotlinc_rules(),
            *source_files.rules(),
            *target_types_rules(),
            *testutil.rules(),
            *util_rules(),
            QueryRule(CheckResults, (KotlincCheckRequest,)),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(FallibleClasspathEntry, (CompileKotlinSourceRequest,)),
            QueryRule(RenderedClasspath, (CompileKotlinSourceRequest,)),
            QueryRule(ClasspathEntry, (CompileKotlinSourceRequest,)),
        ],
        target_types=[JvmArtifactTarget, KotlinSourcesGeneratorTarget],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


DEFAULT_LOCKFILE = TestCoursierWrapper(
    CoursierResolvedLockfile(
        (
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.jetbrains.kotlin", artifact="kotlin-stdlib", version="1.6.0"
                ),
                file_name="org.jetbrains.kotlin_kotlin-stdlib_1.6.0.jar",
                direct_dependencies=Coordinates(
                    [
                        Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-stdlib-common",
                            version="1.6.0",
                        ),
                        Coordinate(
                            group="org.jetbrains.annotations",
                            artifact="annotations",
                            version="13.0",
                        ),
                    ]
                ),
                dependencies=Coordinates(),
                file_digest=FileDigest(
                    "115daea30b0d484afcf2360237b9d9537f48a4a2f03f3cc2a16577dfc6e90342", 1508076
                ),
            ),
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.jetbrains.kotlin", artifact="kotlin-stdlib-common", version="1.6.0"
                ),
                file_name="org.jetbrains.kotlin_kotlin-stdlib-common_1.6.0.jar",
                direct_dependencies=Coordinates(),
                dependencies=Coordinates(),
                file_digest=FileDigest(
                    "644a7257c23b51a1fd5068960e40922e3e52c219f11ece3e040a3abc74823f22", 200616
                ),
            ),
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.jetbrains.annotations", artifact="annotations", version="13.0"
                ),
                file_name="org.jetbrains.annotations_annotations_13.0.jar",
                direct_dependencies=Coordinates(),
                dependencies=Coordinates(),
                file_digest=FileDigest(
                    "ace2a10dc8e2d5fd34925ecac03e4988b2c0f851650c94b8cef49ba1bd111478", 17536
                ),
            ),
        )
    )
).serialize(
    [
        ArtifactRequirement(
            coordinate=Coordinate(
                group="org.jetbrains.kotlin", artifact="kotlin-stdlib", version="1.6.0"
            )
        ),
    ]
)


DEFAULT_KOTLIN_STDLIB_TARGET = dedent(
    """\
    jvm_artifact(
      name="org.jetbrains.kotlin_kotlin-stdlib_1.6.0",
      group="org.jetbrains.kotlin",
      artifact="kotlin-stdlib",
      version="1.6.0",
    )
    """
)


KOTLIN_LIB_SOURCE = dedent(
    """
    package org.pantsbuild.example.lib

    class C {
        val hello = "hello!"
    }
    """
)


KOTLIN_LIB_MAIN_SOURCE = dedent(
    """
    package org.pantsbuild.example

    import org.pantsbuild.example.lib.C

    fun main(args: Array<String>) {
        val c = C()
        println(c.hello)
    }
    """
)


@maybe_skip_jdk_test
def test_compile_no_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'lib',
                )
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGET,
            "3rdparty/jvm/default.lock": DEFAULT_LOCKFILE,
            "ExampleLib.kt": KOTLIN_LIB_SOURCE,
        }
    )
    coarsened_target = expect_single_expanded_coarsened_target(
        rule_runner, Address(spec_path="", target_name="lib")
    )

    classpath = rule_runner.request(
        RenderedClasspath,
        [CompileKotlinSourceRequest(component=coarsened_target, resolve=make_resolve(rule_runner))],
    )
    assert classpath.content == {
        ".ExampleLib.kt.lib.kotlin.jar": {
            "META-INF/MANIFEST.MF",
            "META-INF/main.kotlin_module",
            "org/pantsbuild/example/lib/C.class",
        }
    }

    # Additionally validate that `check` works.
    check_results = rule_runner.request(
        CheckResults,
        [
            KotlincCheckRequest(
                [KotlincCheckRequest.field_set_type.create(coarsened_target.representative)]
            )
        ],
    )
    assert len(check_results.results) == 1
    check_result = check_results.results[0]
    assert check_result.exit_code == 0


@maybe_skip_jdk_test
def test_compile_with_deps(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'main',
                    dependencies = [
                        'lib:lib',
                        # TODO: Remove this once kotlin stdlib dep is injected.
                        "3rdparty/jvm:org.jetbrains.kotlin_kotlin-stdlib_1.6.0",
                    ]
                )
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGET,
            "3rdparty/jvm/default.lock": DEFAULT_LOCKFILE,
            "Example.kt": KOTLIN_LIB_MAIN_SOURCE,
            "lib/BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'lib',
                    dependencies = [
                        # TODO: Remove this once kotlin stdlib dep is injected.
                        "3rdparty/jvm:org.jetbrains.kotlin_kotlin-stdlib_1.6.0",
                    ],
                )
                """
            ),
            "lib/ExampleLib.kt": KOTLIN_LIB_SOURCE,
        }
    )
    classpath = rule_runner.request(
        RenderedClasspath,
        [
            CompileKotlinSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main")
                ),
                resolve=make_resolve(rule_runner),
            )
        ],
    )
    assert classpath.content == {
        ".Example.kt.main.kotlin.jar": {
            "META-INF/MANIFEST.MF",
            "META-INF/main.kotlin_module",
            "org/pantsbuild/example/ExampleKt.class",
        }
    }


@maybe_skip_jdk_test
def test_compile_with_missing_dep_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'main',
                    dependencies = [
                        # TODO: Remove this once kotlin stdlib dep is injected.
                        "3rdparty/jvm:org.jetbrains.kotlin_kotlin-stdlib_1.6.0",
                    ],
                )
                """
            ),
            "Example.kt": KOTLIN_LIB_MAIN_SOURCE,
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGET,
            "3rdparty/jvm/default.lock": DEFAULT_LOCKFILE,
        }
    )
    request = CompileKotlinSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleClasspathEntry, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "Example.kt:4:31: error: unresolved reference: lib" in fallible_result.stderr


@maybe_skip_jdk_test
def test_compile_with_maven_deps(rule_runner: RuleRunner) -> None:
    joda_coord = Coordinate(group="joda-time", artifact="joda-time", version="2.10.10")
    kotlin_stdlib_coord = Coordinate(
        group="org.jetbrains.kotlin", artifact="kotlin-stdlib", version="1.6.0"
    )
    resolved_joda_lockfile = TestCoursierWrapper.new(
        entries=(
            CoursierLockfileEntry(
                coord=joda_coord,
                file_name="joda-time-2.10.10.jar",
                direct_dependencies=Coordinates([]),
                dependencies=Coordinates([]),
                file_digest=FileDigest(
                    fingerprint="dd8e7c92185a678d1b7b933f31209b6203c8ffa91e9880475a1be0346b9617e3",
                    serialized_bytes_length=644419,
                ),
            ),
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.jetbrains.kotlin", artifact="kotlin-stdlib", version="1.6.0"
                ),
                file_name="org.jetbrains.kotlin_kotlin-stdlib_1.6.0.jar",
                direct_dependencies=Coordinates(
                    [
                        Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-stdlib-common",
                            version="1.6.0",
                        ),
                        Coordinate(
                            group="org.jetbrains.annotations",
                            artifact="annotations",
                            version="13.0",
                        ),
                    ]
                ),
                dependencies=Coordinates(),
                file_digest=FileDigest(
                    "115daea30b0d484afcf2360237b9d9537f48a4a2f03f3cc2a16577dfc6e90342", 1508076
                ),
            ),
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.jetbrains.kotlin", artifact="kotlin-stdlib-common", version="1.6.0"
                ),
                file_name="org.jetbrains.kotlin_kotlin-stdlib-common_1.6.0.jar",
                direct_dependencies=Coordinates(),
                dependencies=Coordinates(),
                file_digest=FileDigest(
                    "644a7257c23b51a1fd5068960e40922e3e52c219f11ece3e040a3abc74823f22", 200616
                ),
            ),
            CoursierLockfileEntry(
                coord=Coordinate(
                    group="org.jetbrains.annotations", artifact="annotations", version="13.0"
                ),
                file_name="org.jetbrains.annotations_annotations_13.0.jar",
                direct_dependencies=Coordinates(),
                dependencies=Coordinates(),
                file_digest=FileDigest(
                    "ace2a10dc8e2d5fd34925ecac03e4988b2c0f851650c94b8cef49ba1bd111478", 17536
                ),
            ),
        )
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                f"""\
                jvm_artifact(
                    name = "joda-time_joda-time",
                    group = "{joda_coord.group}",
                    artifact = "{joda_coord.artifact}",
                    version = "{joda_coord.version}",
                )
                kotlin_sources(
                    name = 'main',
                    dependencies = [
                        ":joda-time_joda-time",
                        # TODO: Remove this once kotlin stdlib dep is injected.
                        "3rdparty/jvm:org.jetbrains.kotlin_kotlin-stdlib_1.6.0",
                    ],
                )
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGET,
            "3rdparty/jvm/default.lock": resolved_joda_lockfile.serialize(
                [ArtifactRequirement(joda_coord), ArtifactRequirement(kotlin_stdlib_coord)]
            ),
            "Example.kt": dedent(
                """
                package org.pantsbuild.example

                import org.joda.time.DateTime

                fun main(args: Array<String>) {
                    val dt = DateTime()
                    println(dt.getYear())
                }
                """
            ),
        }
    )
    classpath = rule_runner.request(
        RenderedClasspath,
        [
            CompileKotlinSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main")
                ),
                resolve=make_resolve(rule_runner),
            )
        ],
    )
    assert classpath.content == {
        ".Example.kt.main.kotlin.jar": {
            "META-INF/MANIFEST.MF",
            "META-INF/main.kotlin_module",
            "org/pantsbuild/example/ExampleKt.class",
        }
    }


@maybe_skip_jdk_test
def test_compile_with_undeclared_jvm_artifact_target_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'main',
                    dependencies = [
                        # TODO: Remove this once kotlin stdlib dep is injected.
                        "3rdparty/jvm:org.jetbrains.kotlin_kotlin-stdlib_1.6.0",
                    ],
                )
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGET,
            "3rdparty/jvm/default.lock": DEFAULT_LOCKFILE,
            "Example.kt": dedent(
                """
                package org.pantsbuild.example

                import org.joda.time.DateTime

                fun main(args: Array<String>) {
                    val dt = DateTime()
                    println(dt.getYear())
                }
                """
            ),
        }
    )

    request = CompileKotlinSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleClasspathEntry, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "unresolved reference: joda" in fallible_result.stderr


@maybe_skip_jdk_test
def test_compile_with_undeclared_jvm_artifact_dependency_fails(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                jvm_artifact(
                    name = "joda-time_joda-time",
                    group = "joda-time",
                    artifact = "joda-time",
                    version = "2.10.10",
                )
                kotlin_sources(
                    name = 'main',
                    # `joda-time` needs to be here for compile to succeed
                    dependencies = [
                        # TODO: Remove this once kotlin stdlib dep is injected.
                        "3rdparty/jvm:org.jetbrains.kotlin_kotlin-stdlib_1.6.0",
                    ],
                )
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGET,
            "3rdparty/jvm/default.lock": DEFAULT_LOCKFILE,
            "Example.kt": dedent(
                """
                package org.pantsbuild.example

                import org.joda.time.DateTime

                fun main(args: Array<String>): Unit = {
                    val dt = DateTime()
                    println(dt.getYear())
                }
                """
            ),
        }
    )

    request = CompileKotlinSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="", target_name="main")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleClasspathEntry, [request])
    assert fallible_result.result == CompileResult.FAILED and fallible_result.stderr
    assert "unresolved reference: joda" in fallible_result.stderr
