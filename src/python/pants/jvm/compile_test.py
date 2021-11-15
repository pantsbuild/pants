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
from typing import Sequence

import pytest

from pants.backend.java.compile.javac import CompileJavaSourceRequest
from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.dependency_inference.rules import rules as java_dep_inf_rules
from pants.backend.java.target_types import (
    JavaFieldSet,
    JavaGeneratorFieldSet,
    JavaSourcesGeneratorTarget,
)
from pants.backend.java.target_types import rules as java_target_types_rules
from pants.backend.scala.compile.scalac import CompileScalaSourceRequest
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget
from pants.backend.scala.target_types import rules as scala_target_types_rules
from pants.build_graph.address import Address
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import Addresses
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, Target, UnexpandedTargets
from pants.engine.unions import UnionMembership
from pants.jvm import jdk_rules, testutil
from pants.jvm.compile import (
    ClasspathEntry,
    ClasspathEntryRequest,
    ClasspathSourceAmbiguity,
    ClasspathSourceMissing,
)
from pants.jvm.goals.coursier import rules as coursier_rules
from pants.jvm.resolve.coursier_fetch import CoursierFetchRequest
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.resolve.key import CoursierResolveKey
from pants.jvm.target_types import JvmArtifact
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
            QueryRule(UnexpandedTargets, (Addresses,)),
            QueryRule(CoarsenedTargets, (Addresses,)),
            QueryRule(ClasspathEntry, (CompileJavaSourceRequest,)),
            QueryRule(ClasspathEntry, (CompileScalaSourceRequest,)),
        ],
        target_types=[ScalaSourcesGeneratorTarget, JavaSourcesGeneratorTarget, JvmArtifact],
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


class CompileMockSourceRequest(ClasspathEntryRequest):
    field_sets = (JavaFieldSet, JavaGeneratorFieldSet)


@maybe_skip_jdk_test
def test_request_classification(rule_runner: RuleRunner) -> None:
    def classify(
        targets: Sequence[Target],
        members: Sequence[type[ClasspathEntryRequest]],
    ) -> tuple[type[ClasspathEntryRequest], type[ClasspathEntryRequest] | None]:
        req = ClasspathEntryRequest.for_targets(
            UnionMembership({ClasspathEntryRequest: members}),
            CoarsenedTarget(targets, ()),
            CoursierResolveKey("example", "path", EMPTY_DIGEST),
        )
        return (type(req), type(req.prerequisite) if req.prerequisite else None)

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                scala_sources(name='scala')
                java_sources(name='java')
                jvm_artifact(name='jvm_artifact', group='ex', artifact='ex', version='0.0.0')
                """
            ),
        }
    )
    scala, java, jvm_artifact = rule_runner.request(
        UnexpandedTargets,
        [
            Addresses(
                [
                    Address("", target_name="scala"),
                    Address("", target_name="java"),
                    Address("", target_name="jvm_artifact"),
                ]
            )
        ],
    )
    all_members = [CompileJavaSourceRequest, CompileScalaSourceRequest, CoursierFetchRequest]

    # Fully compatible.
    assert (CompileJavaSourceRequest, None) == classify([java], all_members)
    assert (CompileScalaSourceRequest, None) == classify([scala], all_members)
    assert (CoursierFetchRequest, None) == classify([jvm_artifact], all_members)

    # Partially compatible.
    assert (CompileJavaSourceRequest, CompileScalaSourceRequest) == classify(
        [java, scala], all_members
    )
    with pytest.raises(ClasspathSourceMissing):
        classify([java, jvm_artifact], all_members)

    # None compatible.
    with pytest.raises(ClasspathSourceMissing):
        classify([java], [])
    with pytest.raises(ClasspathSourceMissing):
        classify([scala, java, jvm_artifact], all_members)

    # Too many compatible.
    with pytest.raises(ClasspathSourceAmbiguity):
        classify([java], [CompileJavaSourceRequest, CompileMockSourceRequest])


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
