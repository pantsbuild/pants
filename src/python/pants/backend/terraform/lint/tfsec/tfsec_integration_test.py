# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

from pants.backend.terraform import tool
from pants.backend.terraform.lint.tffmt.tffmt import PartitionMetadata
from pants.backend.terraform.lint.tfsec.rules import rules as tfsec_rules
from pants.backend.terraform.lint.tfsec.tfsec import TfSecRequest
from pants.backend.terraform.target_types import (
    TerraformDeploymentTarget,
    TerraformFieldSet,
    TerraformModuleTarget,
)
from pants.core.goals.lint import LintResult
from pants.core.util_rules import source_files
from pants.engine.internals.native_engine import EMPTY_DIGEST, Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def set_up_rule_runner(tfsec_args: list[str]) -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[TerraformModuleTarget, TerraformDeploymentTarget],
        rules=[
            *tfsec_rules(),
            *tool.rules(),
            *source_files.rules(),
            QueryRule(LintResult, (TfSecRequest.Batch,)),
        ],
    )

    rule_runner.set_options(
        [
            *(f"--terraform-tfsec-args='{tfsec_arg}'" for tfsec_arg in tfsec_args),
            "--terraform-tfsec-config=.tfsec_config.json",  # changing the config since changing pants_ignore isn't possible with the rule_runner
        ]
    )

    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                terraform_deployment(name="tgt_good", root_module=":good")
                terraform_module(name="good", sources=["main.tf"])
                """
            ),
            "main.tf": dedent(
                """\
                resource "aws_s3_bucket" "my-bucket" {
                  bucket = "foobar"
                  acl    = "private"
                }
                """
            ),
            ".tfsec_config.json": '{"exclude":["aws-s3-block-public-acls"]}',
        }
    )

    return rule_runner


def test_run_tfsec():
    rule_runner = set_up_rule_runner(["--no-color"])

    target = rule_runner.get_target(Address("", target_name="good"))

    result = rule_runner.request(
        LintResult,
        [TfSecRequest.Batch("tfsec", (TerraformFieldSet.create(target),), PartitionMetadata(""))],
    )

    assert result.exit_code == 1
    assert "1 ignored" in result.stdout, "Error wasn't ignored, did we pull in the config file?"
    assert (
        "\x1b[1m" not in result.stdout
    ), "Found colour control code in ouput, are extra-args being passed?"


async def test_run_tfsec_with_report():
    rule_runner = set_up_rule_runner(["--no-color", "--out=reports/tfsec.txt"])

    target = rule_runner.get_target(Address("", target_name="good"))

    result = rule_runner.request(
        LintResult,
        [TfSecRequest.Batch("tfsec", (TerraformFieldSet.create(target),), PartitionMetadata(""))],
    )

    assert result.exit_code == 1
    assert result.report != EMPTY_DIGEST
    assert (
        "1 file(s) written: reports/tfsec.txt" in result.stderr
    ), "No file was written, are extra args being passed?"
    assert "1 ignored" in result.stdout, "Error wasn't ignored, did we pull in the config file?"
    assert (
        "\x1b[1m" not in result.stdout
    ), "Found colour control code in ouput, are extra-args being passed?"
