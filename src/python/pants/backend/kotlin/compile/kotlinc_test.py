# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.kotlin.compile import kotlinc_plugins
from pants.backend.kotlin.compile.kotlinc import CompileKotlinSourceRequest
from pants.backend.kotlin.compile.kotlinc import rules as kotlinc_rules
from pants.backend.kotlin.compile.testutil import _KOTLIN_VERSION, KOTLIN_STDLIB_REQUIREMENTS
from pants.backend.kotlin.dependency_inference.rules import rules as kotlin_dep_inf_rules
from pants.backend.kotlin.goals.check import KotlincCheckRequest
from pants.backend.kotlin.goals.check import rules as kotlin_check_rules
from pants.backend.kotlin.target_types import KotlincPluginTarget, KotlinSourcesGeneratorTarget
from pants.backend.kotlin.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResults
from pants.core.util_rules import config_files, source_files, system_binaries
from pants.engine.addresses import Addresses
from pants.engine.target import CoarsenedTargets
from pants.jvm import jdk_rules, testutil
from pants.jvm.compile import ClasspathEntry, CompileResult, FallibleClasspathEntry
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
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


@pytest.fixture
def kotlin_stdlib_jvm_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "kotlin-stdlib.test.lock",
        KOTLIN_STDLIB_REQUIREMENTS,
    )


@pytest.fixture
def kotlin_stdlib_jvm_lockfile(
    kotlin_stdlib_jvm_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return kotlin_stdlib_jvm_lockfile_def.load(request)


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
def test_compile_no_deps(
    rule_runner: RuleRunner, kotlin_stdlib_jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'lib',
                )
                """
            ),
            "3rdparty/jvm/BUILD": kotlin_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": kotlin_stdlib_jvm_lockfile.serialized_lockfile,
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
def test_compile_with_deps(
    rule_runner: RuleRunner, kotlin_stdlib_jvm_lockfile: JVMLockfileFixture
) -> None:
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
            "3rdparty/jvm/BUILD": kotlin_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": kotlin_stdlib_jvm_lockfile.serialized_lockfile,
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
def test_compile_with_missing_dep_fails(
    rule_runner: RuleRunner, kotlin_stdlib_jvm_lockfile: JVMLockfileFixture
) -> None:
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
            "3rdparty/jvm/BUILD": kotlin_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": kotlin_stdlib_jvm_lockfile.serialized_lockfile,
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


@pytest.fixture
def kotlin_stdlib_with_joda_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "kotlin-stdlib-with-joda.test.lock",
        ["joda-time:joda-time:2.10.10"] + KOTLIN_STDLIB_REQUIREMENTS,
    )


@pytest.fixture
def kotlin_stdlib_with_joda_lockfile(
    kotlin_stdlib_with_joda_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return kotlin_stdlib_with_joda_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_compile_with_maven_deps(
    rule_runner: RuleRunner, kotlin_stdlib_with_joda_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'main',
                    dependencies = [
                        "3rdparty/jvm:joda-time_joda-time",
                    ],
                )
                """
            ),
            "3rdparty/jvm/BUILD": kotlin_stdlib_with_joda_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": kotlin_stdlib_with_joda_lockfile.serialized_lockfile,
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
def test_compile_with_undeclared_jvm_artifact_target_fails(
    rule_runner: RuleRunner, kotlin_stdlib_jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'main',
                )
                """
            ),
            "3rdparty/jvm/BUILD": kotlin_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": kotlin_stdlib_jvm_lockfile.serialized_lockfile,
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
def test_compile_with_undeclared_jvm_artifact_dependency_fails(
    rule_runner: RuleRunner, kotlin_stdlib_jvm_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                kotlin_sources(
                    name = 'main',
                )
                """
            ),
            "3rdparty/jvm/BUILD": kotlin_stdlib_jvm_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": kotlin_stdlib_jvm_lockfile.serialized_lockfile,
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


@pytest.fixture
def kotlinc_allopen_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "kotlinc-allopen.test.lock",
        [f"org.jetbrains.kotlin:kotlin-allopen:{_KOTLIN_VERSION}"] + KOTLIN_STDLIB_REQUIREMENTS,
    )


@pytest.fixture
def kotlinc_allopen_lockfile(
    kotlinc_allopen_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return kotlinc_allopen_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_compile_with_kotlinc_plugin(
    rule_runner: RuleRunner, kotlinc_allopen_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "lib/BUILD": dedent(
                """\
                kotlinc_plugin(
                    name = "allopen",
                    plugin_id = "org.jetbrains.kotlin.allopen",
                    plugin_args = ["annotation=lib.MarkOpen"],
                    artifact = "3rdparty/jvm:org.jetbrains.kotlin_kotlin-allopen",
                )

                kotlin_sources()
                """
            ),
            "3rdparty/jvm/BUILD": kotlinc_allopen_lockfile.requirements_as_jvm_artifact_targets(),
            "3rdparty/jvm/default.lock": kotlinc_allopen_lockfile.serialized_lockfile,
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
