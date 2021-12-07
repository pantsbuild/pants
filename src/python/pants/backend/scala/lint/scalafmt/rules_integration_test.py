# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.scala import target_types
from pants.backend.scala.compile.scalac import rules as scalac_rules
from pants.backend.scala.lint import scala_lang_fmt
from pants.backend.scala.lint.scalafmt import skip_field
from pants.backend.scala.lint.scalafmt.rules import ScalafmtFieldSet, ScalafmtRequest
from pants.backend.scala.lint.scalafmt.rules import rules as scalafmt_rules
from pants.backend.scala.target_types import ScalaSourcesGeneratorTarget, ScalaSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.jvm import classpath
from pants.jvm.jdk_rules import rules as jdk_rules
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner

NAMED_RESOLVE_OPTIONS = '--jvm-resolves={"test": "coursier_resolve.lockfile"}'
DEFAULT_RESOLVE_OPTION = "--jvm-default-resolve=test"


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
            *scalac_rules(),
            *util_rules(),
            *jdk_rules(),
            *target_types.rules(),
            *scala_lang_fmt.rules(),
            *scalafmt_rules(),
            *skip_field.rules(),
            QueryRule(LintResults, (ScalafmtRequest,)),
            QueryRule(FmtResult, (ScalafmtRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[ScalaSourceTarget, ScalaSourcesGeneratorTarget],
    )
    rule_runner.set_options(
        [
            NAMED_RESOLVE_OPTIONS,
            DEFAULT_RESOLVE_OPTION,
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
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

SCALAFMT_CONF_FILE = """\
version = "3.2.1"
runner.dialect = scala213
"""


def run_scalafmt(
    rule_runner: RuleRunner, targets: list[Target]
) -> tuple[tuple[LintResult, ...], FmtResult]:
    field_sets = [ScalafmtFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [ScalafmtRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            ScalafmtRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Foo.scala": GOOD_FILE,
            "BUILD": "scala_sources(name='t')",
            ".scalafmt.conf": SCALAFMT_CONF_FILE,
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.scala"))
    lint_results, fmt_result = run_scalafmt(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert fmt_result.output == get_digest(rule_runner, {"Foo.scala": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Bar.scala": BAD_FILE,
            "BUILD": "scala_sources(name='t')",
            ".scalafmt.conf": SCALAFMT_CONF_FILE,
        }
    )
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.scala"))
    lint_results, fmt_result = run_scalafmt(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "Bar.scala\n" == lint_results[0].stdout
    assert fmt_result.output == get_digest(rule_runner, {"Bar.scala": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "Foo.scala": GOOD_FILE,
            "Bar.scala": BAD_FILE,
            "BUILD": "scala_sources(name='t')",
            ".scalafmt.conf": SCALAFMT_CONF_FILE,
        }
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.scala")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.scala")),
    ]
    lint_results, fmt_result = run_scalafmt(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "Bar.scala\n" == lint_results[0].stdout
    assert fmt_result.output == get_digest(
        rule_runner, {"Foo.scala": GOOD_FILE, "Bar.scala": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True
