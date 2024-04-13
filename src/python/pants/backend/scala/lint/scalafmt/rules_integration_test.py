# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap
from typing import overload

import pytest

from pants.backend.scala import target_types
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.lint.scalafmt import skip_field
from pants.backend.scala.lint.scalafmt.rules import PartitionInfo, ScalafmtFieldSet, ScalafmtRequest
from pants.backend.scala.lint.scalafmt.rules import rules as scalafmt_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.fmt import FmtResult, Partitions
from pants.core.util_rules import config_files, source_files, stripped_source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.jvm import classpath
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.strip_jar import strip_jar
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


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
            *strip_jar.rules(),
            *scalac_rules(),
            *util_rules(),
            *jdk_rules(),
            *target_types.rules(),
            *scalafmt_rules(),
            *skip_field.rules(),
            QueryRule(Partitions, (ScalafmtRequest.PartitionRequest,)),
            QueryRule(FmtResult, (ScalafmtRequest.Batch,)),
            QueryRule(Snapshot, (PathGlobs,)),
        ],
        target_types=[ScalaSourceTarget, ScalaSourcesGeneratorTarget],
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


GOOD_FILE = """\
package org.pantsbuild.example

object Foo {
  val Foo = 3
}
"""

BAD_FILE = """\
package org.pantsbuild.example

object Bar {
val Foo = 3
}
"""

FIXED_BAD_FILE = """\
package org.pantsbuild.example

object Bar {
  val Foo = 3
}
"""

FIXED_BAD_FILE_INDENT_4 = """\
package org.pantsbuild.example

object Bar {
    val Foo = 3
}
"""

SCALAFMT_CONF_FILENAME = ".scalafmt.conf"

BASIC_SCALAFMT_CONF = """\
version = "3.2.1"
runner.dialect = scala213
"""


@overload
def run_scalafmt(
    rule_runner: RuleRunner, targets: list[Target], expected_partitions: None = None
) -> FmtResult:
    ...


@overload
def run_scalafmt(
    rule_runner: RuleRunner, targets: list[Target], expected_partitions: dict[str, tuple[str, ...]]
) -> list[FmtResult]:
    ...


def run_scalafmt(
    rule_runner: RuleRunner,
    targets: list[Target],
    expected_partitions: dict[str, tuple[str, ...]] | None = None,
) -> FmtResult | list[FmtResult]:
    field_sets = [ScalafmtFieldSet.create(tgt) for tgt in targets]
    partitions = rule_runner.request(
        Partitions[PartitionInfo],
        [
            ScalafmtRequest.PartitionRequest(tuple(field_sets)),
        ],
    )
    if expected_partitions:
        assert len(partitions) == len(expected_partitions)
        for partition in partitions:
            assert partition.metadata is not None

            config_file = partition.metadata.config_snapshot.files[0]
            assert config_file in expected_partitions
            assert partition.elements == expected_partitions[config_file]
    else:
        assert len(partitions) == 1
    fmt_results = [
        rule_runner.request(
            FmtResult,
            [
                ScalafmtRequest.Batch(
                    "",
                    partition.elements,
                    partition_metadata=partition.metadata,
                    snapshot=rule_runner.request(Snapshot, [PathGlobs(partition.elements)]),
                )
            ],
        )
        for partition in partitions
    ]
    return fmt_results if expected_partitions else fmt_results[0]


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Foo.scala": GOOD_FILE,
            "BUILD": "scala_sources(name='t')",
            ".scalafmt.conf": BASIC_SCALAFMT_CONF,
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.scala"))
    fmt_result = run_scalafmt(rule_runner, [tgt])
    assert fmt_result.output == rule_runner.make_snapshot({"Foo.scala": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Bar.scala": BAD_FILE,
            "BUILD": "scala_sources(name='t')",
            ".scalafmt.conf": BASIC_SCALAFMT_CONF,
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.scala"))
    fmt_result = run_scalafmt(rule_runner, [tgt])
    assert fmt_result.output == rule_runner.make_snapshot({"Bar.scala": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Foo.scala": GOOD_FILE,
            "Bar.scala": BAD_FILE,
            "BUILD": "scala_sources(name='t')",
            ".scalafmt.conf": BASIC_SCALAFMT_CONF,
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.scala")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.scala")),
    ]
    fmt_result = run_scalafmt(rule_runner, tgts)
    assert fmt_result.output == rule_runner.make_snapshot(
        {"Foo.scala": GOOD_FILE, "Bar.scala": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True


def test_multiple_config_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            SCALAFMT_CONF_FILENAME: BASIC_SCALAFMT_CONF,
            "foo/BUILD": "scala_sources()",
            "foo/Foo.scala": GOOD_FILE,
            "foo/bar/BUILD": "scala_sources()",
            "foo/bar/Bar.scala": BAD_FILE,
            f"foo/bar/{SCALAFMT_CONF_FILENAME}": textwrap.dedent(
                f"""\
                {BASIC_SCALAFMT_CONF}
                indent.main = 4
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
    fmt_results = run_scalafmt(
        rule_runner,
        tgts,
        expected_partitions={
            SCALAFMT_CONF_FILENAME: ("foo/Foo.scala",),
            "foo/bar/" + SCALAFMT_CONF_FILENAME: ("foo/bar/Bar.scala",),
        },
    )
    assert not fmt_results[0].did_change
    assert fmt_results[0].output == rule_runner.make_snapshot({"foo/Foo.scala": GOOD_FILE})
    assert fmt_results[1].did_change
    assert fmt_results[1].output == rule_runner.make_snapshot(
        {"foo/bar/Bar.scala": FIXED_BAD_FILE_INDENT_4}
    )
