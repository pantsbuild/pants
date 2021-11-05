# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Tests of multi-language JVM compilation.

Tests of individual compilers should generally be written directly against the relevant `@rules`,
without any other language's `@rule`s present (to ensure that they work as expected in isolation).
But this module should include `@rules` for multiple languages, even though the module that it tests
(`compile.py`) only uses them indirectly via the `ClasspathEntryRequest` `@union`.
"""

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import CompileJavaSourceRequest
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import JavaSourcesGeneratorTarget
from pants.backend.java.target_types import rules as java_target_types_rules
from pants.backend.scala.compile.scalac import CompileScalaSourceRequest
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.target import CoarsenedTargets
from pants.jvm import jdk_rules, testutil
from pants.jvm.compile import ClasspathEntry, FallibleClasspathEntry
from pants.jvm.goals.coursier import rules as coursier_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
    maybe_skip_jdk_test,
)
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner

NAMED_RESOLVE_OPTIONS = '--jvm-resolves={"test": "coursier_resolve.lockfile"}'
DEFAULT_RESOLVE_OPTION = "--jvm-default-resolve=test"


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *java_dep_inf_rules(),
            *javac_rules(),
            *jdk_rules.rules(),
            *scalac_rules(),
            *source_files.rules(),
            *scala_target_types_rules(),
            *java_target_types_rules(),
            *util_rules(),
            *testutil.rules(),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(ClasspathEntry, (CompileJavaSourceRequest,)),
            QueryRule(ClasspathEntry, (CompileScalaSourceRequest,)),
            QueryRule(FallibleClasspathEntry, (CompileJavaSourceRequest,)),
            QueryRule(FallibleClasspathEntry, (CompileScalaSourceRequest,)),
        ],
        target_types=[ScalaSourcesGeneratorTarget, JavaSourcesGeneratorTarget],
    )
    rule_runner.set_options(
        args=[
            NAMED_RESOLVE_OPTIONS,
            DEFAULT_RESOLVE_OPTION,
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


JAVA_LIB_SOURCE = dedent(
    """
    package org.pantsbuild.example.lib;

    public class C {
        public static String HELLO = "hello!";
    }
    """
)

SCALA_MAIN_SOURCE = dedent(
    """
    package org.pantsbuild.example

    import org.pantsbuild.example.lib.C

    object Main {
        def main(args: Array[String]): Unit = {
            println(C.HELLO)
        }
    }
    """
)


@maybe_skip_jdk_test
def test_compile_mixed(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(
                    name = 'main',
                    dependencies = [
                        'lib/C.java',
                    ]
                )
                """
            ),
            "coursier_resolve.lockfile": "[]",
            "Example.scala": SCALA_MAIN_SOURCE,
            "lib/BUILD": "java_sources()",
            "lib/C.java": JAVA_LIB_SOURCE,
        }
    )
    compiled_classfiles = rule_runner.request(
        ClasspathEntry,
        [
            CompileScalaSourceRequest(
                component=expect_single_expanded_coarsened_target(
                    rule_runner, Address(spec_path="", target_name="main")
                ),
                resolve=make_resolve(rule_runner),
            )
        ],
    )
    classpath = rule_runner.request(RenderedClasspath, [compiled_classfiles.digest])
    assert classpath.content == {
        ".Example.scala.main.jar": {
            "META-INF/MANIFEST.MF",
            "org/pantsbuild/example/Main$.class",
            "org/pantsbuild/example/Main.class",
        }
    }
