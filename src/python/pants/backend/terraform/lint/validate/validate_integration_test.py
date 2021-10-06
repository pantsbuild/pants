# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap
from typing import List, Sequence

import pytest

from pants.backend.terraform import style, tool
from pants.backend.terraform.lint import fmt
from pants.backend.terraform.lint.validate import validate
from pants.backend.terraform.lint.validate.validate import ValidateRequest
from pants.backend.terraform.target_types import TerraformFieldSet, TerraformModuleTarget
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
        target_types=[TerraformModuleTarget],
        rules=[
            *external_tool.rules(),
            *fmt.rules(),
            *validate.rules(),
            *tool.rules(),
            *style.rules(),
            *source_files.rules(),
            QueryRule(LintResults, (ValidateRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
    )


GOOD_SOURCE = FileContent(
    "good.tf",
    textwrap.dedent(
        """
        locals {
          good_base = "xyzzy"
          foo       = "${local.good_base}"
        }
        """
    ).encode("utf-8"),
)

# The invalid part is the use of interpolation solely for a variable.
BAD_SOURCE = FileContent(
    "bad.tf",
    textwrap.dedent(
        """
        locals {
          bad_base = "xyzzy"
          bar = "${bad_base}"
        }
        """
    ).encode("utf-8"),
)


def make_target(
    rule_runner: RuleRunner, source_files: List[FileContent], *, target_name="target"
) -> Target:
    files = {
        "BUILD": f"terraform_module(name='{target_name}')\n",
    }
    files.update({source_file.path: source_file.content.decode() for source_file in source_files})
    rule_runner.write_files(files)  # type: ignore[arg-type]
    return rule_runner.get_target(Address("", target_name=target_name))


def run_terraform_validate(
    rule_runner: RuleRunner,
    targets: List[Target],
    *,
    skip: bool = False,
) -> Sequence[LintResult]:
    args = [
        "--backend-packages=pants.backend.experimental.terraform",
        "--backend-packages=pants.backend.experimental.terraform.lint.validate",
    ]
    if skip:
        args.append("--terraform-validate-skip")
    rule_runner.set_options(args)
    field_sets = [TerraformFieldSet.create(tgt) for tgt in targets]
    lint_results = rule_runner.request(LintResults, [ValidateRequest(field_sets)])
    return lint_results.results


def get_content(rule_runner: RuleRunner, digest: Digest) -> DigestContents:
    return rule_runner.request(DigestContents, [digest])


def get_digest(rule_runner: RuleRunner, source_files: List[FileContent]) -> Digest:
    return rule_runner.request(Digest, [CreateDigest(source_files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    lint_results = run_terraform_validate(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 0
    assert lint_results[0].stderr == ""


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results = run_terraform_validate(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.tf" in lint_results[0].stderr


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    lint_results = run_terraform_validate(rule_runner, [target])
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.tf" in lint_results[0].stderr
    assert "good.tf" not in lint_results[0].stderr


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE], target_name="tgt_good"),
        make_target(rule_runner, [BAD_SOURCE], target_name="tgt_bad"),
    ]
    lint_results = run_terraform_validate(rule_runner, targets)
    assert len(lint_results) == 1
    assert lint_results[0].exit_code == 1
    assert "bad.tf" in lint_results[0].stderr
    assert "good.tf" not in lint_results[0].stderr


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results = run_terraform_validate(rule_runner, [target], skip=True)
    assert not lint_results
