# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap
from typing import Sequence

import pytest

from pants.backend.terraform import tool
from pants.backend.terraform.goals import check
from pants.backend.terraform.goals.check import TerraformCheckRequest
from pants.backend.terraform.target_types import TerraformFieldSet, TerraformModuleTarget
from pants.core.goals.check import CheckResult, CheckResults
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
            *check.rules(),
            *tool.rules(),
            *source_files.rules(),
            QueryRule(CheckResults, (TerraformCheckRequest,)),
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

# This resource uses the null_resource provider. Terraform will need to run `init` to init the provider
SOURCE_WITH_PROVIDER = FileContent(
    "provided.tf",
    textwrap.dedent(
        """
        resource "null_resource" "dep" {}
        """
    ).encode("utf-8"),
)


def make_target(
    rule_runner: RuleRunner, source_files: list[FileContent], *, target_name="target"
) -> Target:
    files = {
        "BUILD": f"terraform_module(name='{target_name}')\n",
    }
    files.update({source_file.path: source_file.content.decode() for source_file in source_files})
    rule_runner.write_files(files)
    return rule_runner.get_target(Address("", target_name=target_name))


def run_terraform_validate(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    args: list[str] | None = None,
) -> Sequence[CheckResult]:
    rule_runner.set_options(args or ())
    field_sets = [TerraformFieldSet.create(tgt) for tgt in targets]
    check_results = rule_runner.request(CheckResults, [TerraformCheckRequest(field_sets)])
    return check_results.results


def get_content(rule_runner: RuleRunner, digest: Digest) -> DigestContents:
    return rule_runner.request(DigestContents, [digest])


def get_digest(rule_runner: RuleRunner, source_files: list[FileContent]) -> Digest:
    return rule_runner.request(Digest, [CreateDigest(source_files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    check_results = run_terraform_validate(rule_runner, [target])
    assert len(check_results) == 1
    assert check_results[0].exit_code == 0
    assert check_results[0].stderr == ""


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    check_results = run_terraform_validate(rule_runner, [target])
    assert len(check_results) == 1
    assert check_results[0].exit_code == 1
    assert "bad.tf" in check_results[0].stderr


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    check_results = run_terraform_validate(rule_runner, [target])
    assert len(check_results) == 1
    assert check_results[0].exit_code == 1
    assert "bad.tf" in check_results[0].stderr
    assert "good.tf" not in check_results[0].stderr


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    targets = [
        make_target(rule_runner, [GOOD_SOURCE], target_name="tgt_good"),
        make_target(rule_runner, [BAD_SOURCE], target_name="tgt_bad"),
    ]
    check_results = run_terraform_validate(rule_runner, targets)
    assert len(check_results) == 1
    assert check_results[0].exit_code == 1
    assert "bad.tf" in check_results[0].stderr
    assert "good.tf" not in check_results[0].stderr


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results = run_terraform_validate(rule_runner, [target], args=["--terraform-validate-skip"])
    assert not lint_results


def test_with_dependency(rule_runner: RuleRunner) -> None:
    """Sources with a provider need to have `terraform init` run before to initialise the provider.

    Without `init`, `terraform validate` fails. It is therefore sufficient to just test that the
    process ran successfully
    """
    targets = [make_target(rule_runner, [SOURCE_WITH_PROVIDER])]
    check_results = run_terraform_validate(rule_runner, targets)
    assert check_results[0].exit_code == 0
