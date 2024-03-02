# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent
from typing import Any, Callable, TypeVar, overload

import pytest

from internal_plugins.test_lockfile_fixtures.lockfile_fixture import (
    JVMLockfileFixture,
    JVMLockfileFixtureDefinition,
)
from pants.backend.scala import target_types
from pants.backend.scala.compile import scalac
from pants.backend.scala.lint.scalafix import extra_fields
from pants.backend.scala.lint.scalafix.rules import (
    ScalafixFieldSet,
    ScalafixFixRequest,
    ScalafixLintRequest,
    ScalafixPartitionInfo,
)
from pants.backend.scala.lint.scalafix.rules import rules as scalafix_rules
from pants.backend.scala.lint.scalafix.subsystem import DEFAULT_SCALAFIX_CONFIG_FILENAME
from pants.backend.scala.resolve.artifact import rules as scala_artifact_rules
from pants.backend.scala.target_types import (
    ScalacPluginTarget,
    ScalaSourcesGeneratorTarget,
    ScalaSourceTarget,
)
from pants.build_graph.address import Address
from pants.core.goals.fix import FixResult
from pants.core.goals.fmt import Partitions
from pants.core.goals.lint import LintResult
from pants.core.util_rules import config_files, source_files, stripped_source_files, system_binaries
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.core.util_rules.partitions import Partition
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.jvm import classpath
from pants.jvm.dependency_inference import artifact_mapper
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.target_types import JvmArtifactTarget
from pants.jvm.testutil import maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner, logging


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *config_files.rules(),
            *classpath.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *source_files.rules(),
            *stripped_source_files.rules(),
            *artifact_mapper.rules(),
            *strip_jar.rules(),
            *scalac.rules(),
            *util_rules(),
            *jdk_rules(),
            *target_types.rules(),
            *scala_artifact_rules(),
            *scalafix_rules(),
            *extra_fields.rules(),
            *system_binaries.rules(),
            QueryRule(Partitions, (ScalafixFixRequest.PartitionRequest,)),
            QueryRule(Partitions, (ScalafixLintRequest.PartitionRequest,)),
            QueryRule(FixResult, (ScalafixFixRequest.Batch,)),
            QueryRule(LintResult, (ScalafixLintRequest.Batch,)),
            QueryRule(Snapshot, (PathGlobs,)),
        ],
        target_types=[
            ScalaSourceTarget,
            ScalacPluginTarget,
            ScalaSourcesGeneratorTarget,
            JvmArtifactTarget,
        ],
    )
    return rule_runner


@overload
def run_scalafix_fix(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_options: list[str] = [],
    expected_partitions: None = None,
) -> FixResult:
    ...


@overload
def run_scalafix_fix(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_options: list[str] = [],
    expected_partitions: dict[str, tuple[str, ...]],
) -> list[FixResult]:
    ...


def run_scalafix_fix(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_options: list[str] = [],
    expected_partitions: dict[str, tuple[str, ...]] | None = None,
) -> FixResult | list[FixResult]:
    def create_batch_request(
        name: str, partition: Partition[str, ScalafixPartitionInfo]
    ) -> ScalafixFixRequest.Batch:
        snapshot = rule_runner.request(Snapshot, [PathGlobs(partition.elements)])
        return ScalafixFixRequest.Batch(
            name,
            partition.elements,
            partition_metadata=partition.metadata,
            snapshot=snapshot,
        )

    return _run_scalafix(
        rule_runner,
        targets,
        output_type=FixResult,
        paritition_req_call=lambda x: ScalafixFixRequest.PartitionRequest(x),
        batch_req_call=create_batch_request,
        extra_options=extra_options,
        expected_partitions=expected_partitions,
    )


@overload
def run_scalafix_lint(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_options: list[str] = [],
    expected_partitions: None = None,
) -> LintResult:
    ...


@overload
def run_scalafix_lint(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_options: list[str] = [],
    expected_partitions: dict[str, tuple[str, ...]],
) -> list[LintResult]:
    ...


def run_scalafix_lint(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    extra_options: list[str] = [],
    expected_partitions: dict[str, tuple[str, ...]] | None = None,
) -> LintResult | list[LintResult]:
    def create_batch_request(
        name: str, partition: Partition[str, ScalafixPartitionInfo]
    ) -> ScalafixLintRequest.Batch:
        return ScalafixLintRequest.Batch(
            name, partition.elements, partition_metadata=partition.metadata
        )

    return _run_scalafix(
        rule_runner,
        targets,
        output_type=LintResult,
        paritition_req_call=lambda x: ScalafixLintRequest.PartitionRequest(x),
        batch_req_call=create_batch_request,
        extra_options=extra_options,
        expected_partitions=expected_partitions,
    )


_Out = TypeVar("_Out")


def _run_scalafix(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    output_type: type[_Out],
    paritition_req_call: Callable[[tuple[ScalafixFieldSet, ...]], Any],
    batch_req_call: Callable[[str, Partition[str, ScalafixPartitionInfo]], Any],
    extra_options: list[str] = [],
    expected_partitions: dict[str, tuple[str, ...]] | None = None,
) -> _Out | list[_Out]:
    rule_runner.set_options(extra_options, env_inherit=PYTHON_BOOTSTRAP_ENV)

    field_sets = [ScalafixFieldSet.create(tgt) for tgt in targets]
    partitions = rule_runner.request(
        Partitions[ScalafixPartitionInfo], [paritition_req_call(tuple(field_sets))]
    )

    results = [
        rule_runner.request(
            output_type,
            [batch_req_call("scalafix", partition)],
        )
        for partition in partitions
    ]
    return results if expected_partitions else results[0]


BASIC_SCALAFIX_CONF = dedent(
    """\
    rules = [ DisableSyntax ]
    """
)

GOOD_FILE = """\
object Foo {
  def hello = "hello"
}
"""

BAD_FILE = """\
object Foo {
  def throwException = throw new IllegalArgumentException
}
"""

BAD_FILE_STDOUT = """\
Foo.scala:2:24: error: [DisableSyntax.throw] exceptions should be avoided, consider encoding the error in the return type instead
  def throwException = throw new IllegalArgumentException
                       ^^^^^
"""


@maybe_skip_jdk_test
def test_lint_failure(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Foo.scala": BAD_FILE,
            "BUILD": "scala_sources(name='test')",
            ".scalafix.conf": dedent(
                """\
                rules = [ DisableSyntax ]
                DisableSyntax.noThrows = true
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="test", relative_file_path="Foo.scala"))

    lint_result = run_scalafix_lint(
        rule_runner,
        [tgt],
        extra_options=["--scalafix-semantic-rules=False"],
    )

    assert lint_result.stdout == BAD_FILE_STDOUT
    assert lint_result.exit_code != 0


@maybe_skip_jdk_test
def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Foo.scala": BAD_FILE,
            "Bar.scala": GOOD_FILE,
            "BUILD": "scala_sources(name='test')",
            ".scalafix.conf": dedent(
                """\
                rules = [ DisableSyntax ]
                DisableSyntax.noThrows = true
                """
            ),
        }
    )

    tgts = [
        rule_runner.get_target(Address("", target_name="test", relative_file_path="Foo.scala")),
        rule_runner.get_target(Address("", target_name="test", relative_file_path="Bar.scala")),
    ]

    lint_result = run_scalafix_lint(
        rule_runner,
        tgts,
        extra_options=["--scalafix-semantic-rules=False"],
    )
    assert lint_result.exit_code != 0


@maybe_skip_jdk_test
def test_multiple_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            DEFAULT_SCALAFIX_CONFIG_FILENAME: BASIC_SCALAFIX_CONF,
            "foo/BUILD": "scala_sources()",
            "foo/Foo.scala": GOOD_FILE,
            "foo/bar/BUILD": "scala_sources()",
            "foo/bar/Bar.scala": BAD_FILE,
            f"foo/bar/{DEFAULT_SCALAFIX_CONFIG_FILENAME}": dedent(
                f"""\
                {BASIC_SCALAFIX_CONF}
                DisableSyntax.noThrows = true
                """
            ),
        }
    )

    tgts = [
        rule_runner.get_target(Address("foo", target_name="foo", relative_file_path="Foo.scala")),
        rule_runner.get_target(
            Address("foo/bar", target_name="bar", relative_file_path="Bar.scala")
        ),
    ]
    lint_results = run_scalafix_lint(
        rule_runner,
        tgts,
        extra_options=["--scalafix-semantic-rules=False"],
        expected_partitions={
            DEFAULT_SCALAFIX_CONFIG_FILENAME: ("foo/Foo.scala",),
            "foo/bar/" + DEFAULT_SCALAFIX_CONFIG_FILENAME: ("foo/bar/Bar.scala",),
        },
    )

    assert lint_results[0].exit_code == 0
    assert lint_results[1].exit_code != 0


@pytest.fixture
def semanticdb_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "semanticdb-scalac-2.13.12.test.lock",
        ["org.scala-lang:scala-library:2.13.12", "org.scalameta:semanticdb-scalac_2.13.12:4.8.14"],
    )


@pytest.fixture
def semanticdb_lockfile(
    semanticdb_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return semanticdb_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_builtin_semanticdb_rule(
    rule_runner: RuleRunner, semanticdb_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": semanticdb_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": semanticdb_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/Foo.scala": dedent(
                """\
                import scala.List
                import scala.collection.{immutable, mutable}
                object Foo { immutable.Seq.empty[Int] }
                """
            ),
            "src/jvm/BUILD": dedent(
                """\
                scalac_plugin(
                  name="semanticdb",
                  artifact="//3rdparty/jvm:org.scalameta_semanticdb-scalac_2.13.12"
                )

                scala_sources(scalac_plugins=["semanticdb"])
                """
            ),
            ".scalafix.conf": "rules = [ RemoveUnused ]",
        }
    )

    tgt = rule_runner.get_target(Address("src/jvm", relative_file_path="Foo.scala"))

    scalac_args = ["-Yrangepos", "-Xlint:unused"]
    fix_result = run_scalafix_fix(
        rule_runner,
        [tgt],
        extra_options=[
            f"--scala-version-for-resolve={repr({'jvm-default': '2.13.12'})}",
            f"--source-root-patterns={repr(['src/jvm'])}",
            f"--scalac-args={repr(scalac_args)}",
        ],
    )
    assert fix_result.output == rule_runner.make_snapshot(
        {
            "src/jvm/Foo.scala": dedent(
                """
                import scala.collection.immutable
                object Foo { immutable.Seq.empty[Int] }
                """
            )
        }
    )
    assert fix_result.did_change is True


@pytest.fixture
def scala_rewrites_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "scala-rewrites-2.13.12.test.lock",
        [
            "org.scala-lang:scala-library:2.13.12",
            "org.scalameta:semanticdb-scalac_2.13.12:4.8.14",
            "org.scala-lang:scala-rewrites_2.13:0.1.5",
        ],
    )


@pytest.fixture
def scala_rewrites_lockfile(
    scala_rewrites_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scala_rewrites_lockfile_def.load(request)


@logging
@maybe_skip_jdk_test
def test_run_custom_rule(
    rule_runner: RuleRunner, scala_rewrites_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": scala_rewrites_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scala_rewrites_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/Foo.scala": dedent(
                """\
                object Foo {
                    def hello = "hello"
                    def nil = Nil + hello
                }
                """
            ),
            "src/jvm/BUILD": dedent(
                """\
                scalac_plugin(
                  name="semanticdb",
                  artifact="//3rdparty/jvm:org.scalameta_semanticdb-scalac_2.13.12"
                )

                scala_sources(name='test', scalac_plugins=["semanticdb"])
                """
            ),
            ".scalafix.conf": "rules = [ fix.scala213.Any2StringAdd ]",
        }
    )

    tgt = rule_runner.get_target(
        Address("src/jvm", target_name="test", relative_file_path="Foo.scala")
    )

    rule_targets = ["3rdparty/jvm:org.scala-lang_scala-rewrites_2.13"]
    scalac_args = ["-Yrangepos", "-deprecation"]
    fix_result = run_scalafix_fix(
        rule_runner,
        [tgt],
        extra_options=[
            f"--scala-version-for-resolve={repr({'jvm-default': '2.13.12'})}",
            f"--source-root-patterns={repr(['src/jvm'])}",
            f"--scalac-args={repr(scalac_args)}",
            f"--scalafix-rule-targets={repr(rule_targets)}",
        ],
    )
    assert fix_result.output == rule_runner.make_snapshot(
        {
            "src/jvm/Foo.scala": dedent(
                """\
                object Foo {
                    def hello = "hello"
                    def nil = String.valueOf(Nil) + hello
                }
                """
            )
        }
    )
    assert fix_result.did_change is True


@pytest.fixture
def scala3_lockfile_def() -> JVMLockfileFixtureDefinition:
    return JVMLockfileFixtureDefinition(
        "scala3.test.lock",
        ["org.scala-lang:scala3-library_3:3.3.1"],
    )


@pytest.fixture
def scala3_lockfile(
    scala3_lockfile_def: JVMLockfileFixtureDefinition, request
) -> JVMLockfileFixture:
    return scala3_lockfile_def.load(request)


@maybe_skip_jdk_test
def test_builtin_syntactic_rule_scala3(
    rule_runner: RuleRunner, scala3_lockfile: JVMLockfileFixture
) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/default.lock": scala3_lockfile.serialized_lockfile,
            "3rdparty/jvm/BUILD": scala3_lockfile.requirements_as_jvm_artifact_targets(),
            "src/jvm/Foo.scala": dedent(
                """\
                object SignificantIndentation:
                    implicit class XtensionVal(val str: String) extends AnyVal:
                        def doubled: String = str + str
                """
            ),
            "src/jvm/BUILD": dedent(
                """\
                scala_sources()
                """
            ),
            ".scalafix.conf": "rules = [ LeakingImplicitClassVal ]",
        }
    )

    tgt = rule_runner.get_target(Address("src/jvm", relative_file_path="Foo.scala"))

    fix_result = run_scalafix_fix(
        rule_runner,
        [tgt],
        extra_options=[
            f"--scala-version-for-resolve={repr({'jvm-default': '3.3.1'})}",
            f"--source-root-patterns={repr(['src/jvm'])}",
            "--scalafix-semantic-rules=False",
        ],
    )

    assert fix_result.output == rule_runner.make_snapshot(
        {
            "src/jvm/Foo.scala": dedent(
                """\
                object SignificantIndentation:
                    implicit class XtensionVal(private val str: String) extends AnyVal:
                        def doubled: String = str + str
                """
            )
        }
    )
    assert fix_result.did_change is True
