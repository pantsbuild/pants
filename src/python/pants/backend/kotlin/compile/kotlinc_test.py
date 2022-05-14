# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

import pytest

from pants.backend.kotlin.compile import kotlinc_plugins
from pants.backend.kotlin.compile.kotlinc import CompileKotlinSourceRequest
from pants.backend.kotlin.compile.kotlinc import rules as kotlinc_rules
from pants.backend.kotlin.dependency_inference.rules import rules as kotlin_dep_inf_rules
from pants.backend.kotlin.goals.check import KotlincCheckRequest
from pants.backend.kotlin.goals.check import rules as kotlin_check_rules
from pants.backend.kotlin.target_types import KotlincPluginTarget, KotlinSourcesGeneratorTarget
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
            *kotlinc_plugins.rules(),
            *kotlin_dep_inf_rules(),
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
        target_types=[JvmArtifactTarget, KotlinSourcesGeneratorTarget, KotlincPluginTarget],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


_DEFAULT_LOCKFILE_ENTRIES = (
    CoursierLockfileEntry(
        coord=Coordinate(group="org.jetbrains.kotlin", artifact="kotlin-stdlib", version="1.6.20"),
        file_name="org.jetbrains.kotlin_kotlin-stdlib_1.6.20.jar",
        direct_dependencies=Coordinates(
            [
                Coordinate(
                    group="org.jetbrains.kotlin",
                    artifact="kotlin-stdlib-common",
                    version="1.6.20",
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
            "eeb51c2b67b26233fd81d0bc4f8044ec849718890905763ceffd84a31e2cb799",
            1509405,
        ),
    ),
    CoursierLockfileEntry(
        coord=Coordinate(
            group="org.jetbrains.kotlin",
            artifact="kotlin-stdlib-common",
            version="1.6.20",
        ),
        file_name="org.jetbrains.kotlin_kotlin-stdlib-common_1.6.20.jar",
        direct_dependencies=Coordinates(),
        dependencies=Coordinates(),
        file_digest=FileDigest(
            "8da40a2520d30dcb1012176fe93d24e82d08a3e346c37e0343b0fb6f64f6be01",
            200631,
        ),
    ),
    CoursierLockfileEntry(
        coord=Coordinate(
            group="org.jetbrains.annotations",
            artifact="annotations",
            version="13.0",
        ),
        file_name="org.jetbrains.annotations_annotations_13.0.jar",
        direct_dependencies=Coordinates(),
        dependencies=Coordinates(),
        file_digest=FileDigest(
            "ace2a10dc8e2d5fd34925ecac03e4988b2c0f851650c94b8cef49ba1bd111478",
            17536,
        ),
    ),
    CoursierLockfileEntry(
        coord=Coordinate(
            group="org.jetbrains.kotlin",
            artifact="kotlin-script-runtime",
            version="1.6.20",
        ),
        file_name="kotlin-script-runtime-1.6.20.jar",
        direct_dependencies=Coordinates(),
        dependencies=Coordinates(),
        file_digest=FileDigest(
            "3fee5cea54449e18ce5a770c3c4849f0f855d8b061f7d0bd2a032110922c0206",
            42319,
        ),
    ),
    CoursierLockfileEntry(
        coord=Coordinate(
            group="org.jetbrains.kotlin",
            artifact="kotlin-reflect",
            version="1.6.20",
        ),
        file_name="kotlin-reflect-1.6.20.jar",
        direct_dependencies=Coordinates(),
        dependencies=Coordinates(),
        file_digest=FileDigest(
            "234b60bd2c49b391ac550afee4ca9a92e485d8c5ae5faa98cdaf7feba1794042",
            3058829,
        ),
    ),
)

_DEFAULT_LOCKFILE_REQUIREMENTS = [
    ArtifactRequirement(
        coordinate=Coordinate(
            group="org.jetbrains.kotlin", artifact="kotlin-stdlib", version="1.6.20"
        )
    ),
    ArtifactRequirement(
        Coordinate(
            group="org.jetbrains.kotlin",
            artifact="kotlin-reflect",
            version="1.6.20",
        )
    ),
    ArtifactRequirement(
        Coordinate(
            group="org.jetbrains.kotlin",
            artifact="kotlin-script-runtime",
            version="1.6.20",
        )
    ),
]

DEFAULT_LOCKFILE = TestCoursierWrapper(
    CoursierResolvedLockfile(entries=_DEFAULT_LOCKFILE_ENTRIES)
).serialize(_DEFAULT_LOCKFILE_REQUIREMENTS)


DEFAULT_KOTLIN_STDLIB_TARGETS = dedent(
    """\
    jvm_artifact(
      name="org.jetbrains.kotlin_kotlin-stdlib_1.6.20",
      group="org.jetbrains.kotlin",
      artifact="kotlin-stdlib",
      version="1.6.20",
    )
    jvm_artifact(
      name="org.jetbrains.kotlin_kotlin-script-runtime_1.6.20",
      group="org.jetbrains.kotlin",
      artifact="kotlin-script-runtime",
      version="1.6.20",
    )
    jvm_artifact(
      name="org.jetbrains.kotlin_kotlin-reflect_1.6.20",
      group="org.jetbrains.kotlin",
      artifact="kotlin-reflect",
      version="1.6.20",
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
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGETS,
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
                    ]
                )
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGETS,
            "3rdparty/jvm/default.lock": DEFAULT_LOCKFILE,
            "Example.kt": KOTLIN_LIB_MAIN_SOURCE,
            "lib/BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'lib',
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
                )
                """
            ),
            "Example.kt": KOTLIN_LIB_MAIN_SOURCE,
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGETS,
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
            *_DEFAULT_LOCKFILE_ENTRIES,
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
                    ],
                )
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGETS,
            "3rdparty/jvm/default.lock": resolved_joda_lockfile.serialize(
                [ArtifactRequirement(joda_coord), *_DEFAULT_LOCKFILE_REQUIREMENTS]
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
                )
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGETS,
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
                )
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGETS,
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


@maybe_skip_jdk_test
def test_compile_with_kotlinc_plugin(rule_runner: RuleRunner) -> None:
    allopen_coord = Coordinate(
        group="org.jetbrains.kotlin", artifact="kotlin-allopen", version="1.6.20"
    )
    rule_runner.write_files(
        {
            "lib/BUILD": dedent(
                f"""\
                jvm_artifact(
                    name = "allopen_lib",
                    group = "{allopen_coord.group}",
                    artifact = "{allopen_coord.artifact}",
                    version = "{allopen_coord.version}",
                )

                kotlinc_plugin(
                    name = "allopen",
                    plugin_id = "org.jetbrains.kotlin.allopen",
                    plugin_args = ["annotation=lib.MarkOpen"],
                    artifact = ":allopen_lib",
                )

                kotlin_sources()
                """
            ),
            "3rdparty/jvm/BUILD": DEFAULT_KOTLIN_STDLIB_TARGETS,
            "3rdparty/jvm/default.lock": TestCoursierWrapper.new(
                entries=(
                    *_DEFAULT_LOCKFILE_ENTRIES,
                    CoursierLockfileEntry(
                        coord=allopen_coord,
                        file_name="kotlin-allopen-1.6.20.jar",
                        direct_dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-gradle-plugin-api",
                                    version="1.6.20",
                                ),
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-gradle-plugin-model",
                                    version="1.6.20",
                                ),
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-native-utils",
                                    version="1.6.20",
                                ),
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-project-model",
                                    version="1.6.20",
                                ),
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-util-io",
                                    version="1.6.20",
                                ),
                            ]
                        ),
                        dependencies=Coordinates(
                            [
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-gradle-plugin-api",
                                    version="1.6.20",
                                ),
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-gradle-plugin-model",
                                    version="1.6.20",
                                ),
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-native-utils",
                                    version="1.6.20",
                                ),
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-project-model",
                                    version="1.6.20",
                                ),
                                Coordinate(
                                    group="org.jetbrains.kotlin",
                                    artifact="kotlin-util-io",
                                    version="1.6.20",
                                ),
                            ]
                        ),
                        file_digest=FileDigest(
                            "5c67ecca01adc53379da238cb3c25b8756d715d69a2a18fa1927512429428559",
                            29365,
                        ),
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-gradle-plugin-api",
                            version="1.6.20",
                        ),
                        file_name="kotlin-gradle-plugin-api-1.6.20.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "dd4c50bc2b9220fff58be27ca78a48bf1e120be5c4be21710a715cefe9a9df53",
                            139597,
                        ),
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-gradle-plugin-model",
                            version="1.6.20",
                        ),
                        file_name="kotlin-gradle-plugin-model-1.6.20.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "add20d08051ce2c1a7cb0c8b0513f8b4580e24437aca39cc6144b23e0dc54709",
                            12666,
                        ),
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-native-utils",
                            version="1.6.20",
                        ),
                        file_name="kotlin-native-utils-1.6.20.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "b58b6f0133a9eb1f5d215418908d945225db27fe7d9cd5997bb6fbd61c998d1e",
                            92706,
                        ),
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-project-model",
                            version="1.6.20",
                        ),
                        file_name="kotlin-project-model-1.6.20.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "5cbabaeb981f0fb6271ce553b8798d5753763f693f57cad88d8325b9a9d30459",
                            64532,
                        ),
                    ),
                    CoursierLockfileEntry(
                        coord=Coordinate(
                            group="org.jetbrains.kotlin",
                            artifact="kotlin-util-io",
                            version="1.6.20",
                        ),
                        file_name="kotlin-util-io-1.6.20.jar",
                        direct_dependencies=Coordinates([]),
                        dependencies=Coordinates([]),
                        file_digest=FileDigest(
                            "dbae46f5376a0cd0239d7be76d2097840215b15dae282e1ac1f8589c36bb9a56",
                            51102,
                        ),
                    ),
                )
            ).serialize(
                [
                    ArtifactRequirement(allopen_coord),
                    *_DEFAULT_LOCKFILE_REQUIREMENTS,
                ]
            ),
            "lib/Grok.kt": dedent(
                """
                package lib

                annotation class MarkOpen

                @MarkOpen
                class A {
                  val value: Boolean = true
                }

                class B: A() {
                  override val value = false
                }
                """
            ),
        }
    )
    rule_runner.set_options(
        args=[
            "--kotlin-version-for-resolve={'jvm-default': '1.6.20'}",
            "--kotlinc-plugins-for-resolve={'jvm-default': 'org.jetbrains.kotlin.allopen'}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    request = CompileKotlinSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="lib", relative_file_path="Grok.kt")
        ),
        resolve=make_resolve(rule_runner),
    )
    fallible_result = rule_runner.request(FallibleClasspathEntry, [request])
    print(f"stdout:\n{fallible_result.stdout}\nstderr:\n{fallible_result.stderr}")
    assert fallible_result.result == CompileResult.SUCCEEDED
