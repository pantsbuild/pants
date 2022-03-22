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
from pants.core.util_rules import source_files, system_binaries, config_files
from pants.engine.addresses import Addresses
from pants.engine.fs import FileDigest
from pants.engine.target import CoarsenedTargets
from pants.jvm import jdk_rules, testutil
from pants.jvm.compile import ClasspathEntry, FallibleClasspathEntry
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.common import ArtifactRequirement, Coordinate, Coordinates
from pants.jvm.resolve.coursier_fetch import CoursierLockfileEntry, CoursierResolvedLockfile
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
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
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules


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
                direct_dependencies=Coordinates(),
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
        )
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

KOTLIN_LIB_JDK12_SOURCE = dedent(
    """
    package org.pantsbuild.example.lib

    class C {
        val hello = "hello!".indent(4)
    }
    """
)


KOTLIN_LIB_MAIN_SOURCE = dedent(
    """
    package org.pantsbuild.example

    import org.pantsbuild.example.lib.C

    fun main(args: Array<String>) {
        val c = new C()
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
