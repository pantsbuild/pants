# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.lint import java_fmt
from pants.backend.java.lint.google_java_format import rules as gdf_fmt_rules
from pants.backend.java.lint.google_java_format import skip_field
from pants.backend.java.lint.google_java_format.rules import (
    GoogleJavaFormatFieldSet,
    GoogleJavaFormatRequest,
)
from pants.backend.java.target_types import JavaSourcesGeneratorTarget, JavaSourceTarget
from pants.backend.java.target_types import rules as target_types_rules
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
from pants.jvm.jdk_rules import rules as java_util_rules
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
            *javac_rules(),
            *util_rules(),
            *java_util_rules(),
            *target_types_rules(),
            *java_fmt.rules(),
            *gdf_fmt_rules.rules(),
            *skip_field.rules(),
            QueryRule(LintResults, (GoogleJavaFormatRequest,)),
            QueryRule(FmtResult, (GoogleJavaFormatRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
        target_types=[JavaSourceTarget, JavaSourcesGeneratorTarget],
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
package org.pantsbuild.example;

public class Foo {
  public static final String CONSTANT = "Constant changes";
}
"""

BAD_FILE = """\
package org.pantsbuild.example;

public class Bar {
public static final String CONSTANT = "Constant changes";
}
"""

FIXED_BAD_FILE = """\
package org.pantsbuild.example;

public class Bar {
  public static final String CONSTANT = "Constant changes";
}
"""


def run_google_java_format(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[tuple[LintResult, ...], FmtResult]:
    # rule_runner.set_options(
    #     ["--backend-packages=pants.backend.python.lint.black", *(extra_args or ())],
    #     # We propagate LANG and LC_ALL to satisfy click, which black depends upon. Without this we
    #     # see something like the following in CI:
    #     #
    #     # RuntimeError: Click will abort further execution because Python was configured to use
    #     # ASCII as encoding for the environment. Consult
    #     # https://click.palletsprojects.com/unicode-support/ for mitigation steps.
    #     #
    #     # This system supports the C.UTF-8 locale which is recommended. You might be able to
    #     # resolve your issue by exporting the following environment variables:
    #     #
    #     #     export LC_ALL=C.UTF-8
    #     #     export LANG=C.UTF-8
    #     #
    #     env_inherit={"PATH", "PYENV_ROOT", "HOME", "LANG", "LC_ALL"},
    # )
    field_sets = [GoogleJavaFormatFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [GoogleJavaFormatRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.source for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            GoogleJavaFormatRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )
    return lint_results.results, fmt_result


def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_passing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"Foo.java": GOOD_FILE, "BUILD": "java_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.java"))
    lint_results, fmt_result = run_google_java_format(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert fmt_result.output == get_digest(rule_runner, {"Foo.java": GOOD_FILE})
    assert fmt_result.did_change is False


def test_failing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"Bar.java": BAD_FILE, "BUILD": "java_sources(name='t')"})
    tgt = rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.java"))
    lint_results, fmt_result = run_google_java_format(rule_runner, [tgt])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "The following Java files require formatting:\nBar.java\n\n" == lint_results[0].stdout
    assert fmt_result.output == get_digest(rule_runner, {"Bar.java": FIXED_BAD_FILE})
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"Foo.java": GOOD_FILE, "Bar.java": BAD_FILE, "BUILD": "java_sources(name='t')"}
    )
    tgts = [
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Foo.java")),
        rule_runner.get_target(Address("", target_name="t", relative_file_path="Bar.java")),
    ]
    lint_results, fmt_result = run_google_java_format(rule_runner, tgts)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "The following Java files require formatting:\nBar.java\n\n" == lint_results[0].stdout
    assert fmt_result.output == get_digest(
        rule_runner, {"Foo.java": GOOD_FILE, "Bar.java": FIXED_BAD_FILE}
    )
    assert fmt_result.did_change is True
