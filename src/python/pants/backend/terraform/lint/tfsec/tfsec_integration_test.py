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

TFSEC_CUSTOM_ERROR_CODE = "CUS001"
TFSEC_CUSTOM_CHECK = f"""\
checks:
  - code: {TFSEC_CUSTOM_ERROR_CODE}
    description: Custom check taken from the docs, lightly adapted to apply to this test case
    impact: By not having CostCentre we can't keep track of billing
    resolution: Add the CostCentre tag
    requiredTypes:
      - resource
    requiredLabels:
      - aws_s3_bucket
    severity: ERROR
    matchSpec:
      name: tags
      action: contains
      value: CostCentre
    errorMessage: The required CostCentre tag was missing
    relatedLinks:
      - https://aquasecurity.github.io/tfsec/latest/guides/configuration/custom-checks/
"""


def set_up_rule_runner(tfsec_args: list[str]) -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[TerraformModuleTarget, TerraformDeploymentTarget],
        rules=[
            *tfsec_rules(),
            *tool.rules(),
            *source_files.rules(),
            QueryRule(LintResult, (TfSecRequest.Batch,)),
        ],
        bootstrap_args=["--pants-ignore=['!/.tfsec/']"],
    )

    rule_runner.set_options(
        [
            "--terraform-tfsec-args='--no-colour'",
            "--terraform-tfsec-config=.tfsec_config.json",  # the config dir is readable, but we're testing the extra setting
            *tfsec_args,
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
            ".tfsec/custom_tfchecks.yaml": TFSEC_CUSTOM_CHECK,  # this is the default, config discovery should still work even though we've specified a value for the config itself
        }
    )

    return rule_runner


def test_run_tfsec():
    rule_runner = set_up_rule_runner([])

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
    assert (
        TFSEC_CUSTOM_ERROR_CODE.lower() in result.stdout
    ), "Custom check code wasn't found in output, did we pull in our custom config (all files in .tfsec folder)?"


def test_run_tfsec_with_report():
    rule_runner = set_up_rule_runner(
        [
            "--terraform-tfsec-report-name=tfsec.txt",
        ]
    )

    target = rule_runner.get_target(Address("", target_name="good"))

    result = rule_runner.request(
        LintResult,
        [TfSecRequest.Batch("tfsec", (TerraformFieldSet.create(target),), PartitionMetadata(""))],
    )

    assert result.exit_code == 1
    assert (
        "1 file(s) written: reports/tfsec.txt" in result.stderr
    ), "No file was written, are extra args being passed?"
    assert result.report != EMPTY_DIGEST
    assert "1 ignored" in result.stdout, "Error wasn't ignored, did we pull in the config file?"
    assert (
        "\x1b[1m" not in result.stdout
    ), "Found colour control code in ouput, are extra-args being passed?"
