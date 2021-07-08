# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap
from typing import List, Sequence, Tuple

import pytest

from pants.backend.terraform.lint import fmt
from pants.backend.terraform.lint.tffmt import tffmt
from pants.backend.terraform.lint.tffmt.tffmt import TffmtFieldSet, TffmtRequest
from pants.backend.terraform.target_types import TerraformModule
from pants.core.goals.fmt import FmtResult
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import external_tool, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[TerraformModule],
        rules=[
            *external_tool.rules(),
            *fmt.rules(),
            *tffmt.rules(),
            *source_files.rules(),
            QueryRule(LintResults, (TffmtRequest,)),
            QueryRule(FmtResult, (TffmtRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
    )


GOOD_SOURCE = FileContent(
    "good.tf",
    textwrap.dedent(
        """\
    locals {
      foo = "xyzzy"
    }

    resource "test_instance" "default" {
      key        = "value-${local.foo}"
      longer_key = "bar"
    }
    """
    ).encode("utf-8"),
)

# The misformatted part is the `key` property in the resource block.
BAD_SOURCE = FileContent(
    "bad.tf",
    textwrap.dedent(
        """\
    resource "test_instance" "default" {
      key = "foo"
      longer_key = "bar"
    }
    """
    ).encode("utf-8"),
)

FIXED_BAD_SOURCE = FileContent(
    "bad.tf",
    textwrap.dedent(
        """\
    resource "test_instance" "default" {
      key        = "foo"
      longer_key = "bar"
    }
    """
    ).encode("utf-8"),
)


def make_target(
    rule_runner: RuleRunner, source_files: List[FileContent], *, target_name="target"
) -> Target:
    for source_file in source_files:
        rule_runner.create_file(f"{source_file.path}", source_file.content.decode())
    rule_runner.add_to_build_file(
        "",
        f"terraform_module(name='{target_name}')\n",
    )
    return rule_runner.get_target(Address("", target_name=target_name))


def run_tffmt(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    skip: bool = False,
) -> Tuple[Sequence[LintResult], FmtResult]:
    args = ["--backend-packages=pants.backend.experimental.terraform.lint.tffmt"]
    if skip:
        args.append("--terraform-fmt-skip")
    rule_runner.set_options(args)
    field_sets = [TffmtFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [TffmtRequest(field_sets)])
    input_sources = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(field_set.sources for field_set in field_sets),
        ],
    )
    fmt_result = rule_runner.request(
        FmtResult,
        [
            TffmtRequest(field_sets, prior_formatter_result=input_sources.snapshot),
        ],
    )
    return lint_results.results, fmt_result


def get_content(rule_runner: RuleRunner, digest: Digest) -> DigestContents:
    return rule_runner.request(DigestContents, [digest])


def get_digest(rule_runner: RuleRunner, source_files: List[FileContent]) -> Digest:
    return rule_runner.request(Digest, [CreateDigest(source_files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    lint_results, fmt_result = run_tffmt(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""
    assert fmt_result.stdout == ""
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE])
    assert fmt_result.did_change is False


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_tffmt(rule_runner, [target])
    contents = get_content(rule_runner, fmt_result.output)
    print(f">>>{contents[0].content.decode()}<<<")
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 3
    assert "bad.tf" in lint_results[0].stdout
    assert fmt_result.stderr == ""
    assert fmt_result.output == get_digest(rule_runner, [FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    lint_results, fmt_result = run_tffmt(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 3
    assert "bad.tf" in lint_results[0].stdout
    assert "good.tf" not in lint_results[0].stdout
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE], target_name="tgt_good"),
        make_target(rule_runner, [BAD_SOURCE], target_name="tgt_bad"),
    ]
    lint_results, fmt_result = run_tffmt(rule_runner, targets)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 3
    assert "bad.tf" in lint_results[0].stdout
    assert "good.tf" not in lint_results[0].stdout
    assert fmt_result.output == get_digest(rule_runner, [GOOD_SOURCE, FIXED_BAD_SOURCE])
    assert fmt_result.did_change is True


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results, fmt_result = run_tffmt(rule_runner, [target], skip=True)
    assert not lint_results
    assert fmt_result.skipped is True
    assert fmt_result.did_change is False
