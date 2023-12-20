# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.scala import target_types
from pants.backend.scala.compile import scalac
from pants.backend.scala.compile.scalac import CompileScalaSourceRequest
from pants.backend.scala.compile.semanticdb.rules import rules as semanticdb_rules
from pants.backend.scala.resolve.artifact import rules as scala_artifact_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.jvm import classpath, testutil
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve import coursier_fetch, coursier_setup
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import (
    RenderedClasspath,
    expect_single_expanded_coarsened_target,
    make_resolve,
    maybe_skip_jdk_test,
)
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *classpath.rules(),
            *coursier_fetch.rules(),
            *coursier_setup.rules(),
            *source_files.rules(),
            *stripped_source_files.rules(),
            *artifact_mapper.rules(),
            *strip_jar.rules(),
            *scalac.rules(),
            *semanticdb_rules(),
            *util_rules(),
            *jdk_rules(),
            *target_types.rules(),
            *scala_artifact_rules(),
            *testutil.rules(),
            QueryRule(RenderedClasspath, (CompileScalaSourceRequest,)),
        ],
        target_types=[
            ScalaSourceTarget,
            ScalaSourcesGeneratorTarget,
            JvmArtifactTarget,
        ],
    )
    return rule_runner


@pytest.fixture
def scala2_semanticdb_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "semanticdb-scalac-2.13.test.lock",
        ["org.scala-lang:scala-library:2.13.6", "org.scalameta:semanticdb-scalac_2.13.6:4.8.4"],
    )


@pytest.fixture
def scala2_semanticdb_lockfile(
    scala2_semanticdb_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scala2_semanticdb_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_scala2_compile_with_semanticdb(
    rule_runner: RuleRunner, scala2_semanticdb_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": scala2_semanticdb_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scala2_semanticdb_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/Foo.scala": dedent(
                """\
                import scala.collection.immutable
                object Foo { immutable.Seq.empty[Int] }
                """
            ),
            "src/jvm/BUILD": "scala_sources()",
        }
    )

    rule_runner.set_options(
        [f"--source-root-patterns={repr(['src/jvm'])}"], env_inherit=PYTHON_BOOTSTRAP_ENV
    )

    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="src/jvm")
        ),
        resolve=make_resolve(rule_runner),
    )
    rendered_classpath = rule_runner.request(RenderedClasspath, [request])
    assert (
        "META-INF/semanticdb/Foo.scala.semanticdb"
        in rendered_classpath.content["src.jvm.Foo.scala.scalac.jar"]
    )


@pytest.fixture
def scala3_semanticdb_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "semanticdb-scala-3.test.lock",
        ["org.scala-lang:scala3-library_3:3.3.1"],
    )


@pytest.fixture
def scala3_semanticdb_lockfile(
    scala3_semanticdb_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scala3_semanticdb_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_scala3_compile_with_semanticdb(
    rule_runner: RuleRunner, scala3_semanticdb_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": scala3_semanticdb_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scala3_semanticdb_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/Foo.scala": dedent(
                """\
                import scala.collection.immutable
                object Foo { immutable.Seq.empty[Int] }
                """
            ),
            "src/jvm/BUILD": "scala_sources()",
        }
    )

    scala_versions = {"jvm-default": "3.3.1"}
    rule_runner.set_options(
        [
            f"--scala-version-for-resolve={repr(scala_versions)}",
            f"--source-root-patterns={repr(['src/jvm'])}",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    request = CompileScalaSourceRequest(
        component=expect_single_expanded_coarsened_target(
            rule_runner, Address(spec_path="src/jvm")
        ),
        resolve=make_resolve(rule_runner),
    )
    rendered_classpath = rule_runner.request(RenderedClasspath, [request])
    assert (
        "META-INF/semanticdb/Foo.scala.semanticdb"
        in rendered_classpath.content["src.jvm.Foo.scala.scalac.jar"]
    )
