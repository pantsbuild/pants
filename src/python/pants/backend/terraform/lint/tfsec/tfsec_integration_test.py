# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from textwrap import dedent

from pants.backend.terraform import tool
from pants.backend.terraform.lint.tffmt.tffmt import PartitionMetadata
from pants.backend.terraform.lint.tfsec.rules import rules as tfsec_rules
from pants.backend.terraform.lint.tfsec.tfsec import TfSecRequest
from pants.backend.terraform.target_types import (
    TerraformBackendTarget,
    TerraformDeploymentTarget,
    TerraformFieldSet,
    TerraformModuleTarget,
    TerraformVarFileTarget,
)
from pants.core.goals.lint import LintResult
from pants.core.util_rules import source_files
from pants.engine.internals.native_engine import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_run_tfsec():
    rule_runner = RuleRunner(
        target_types=[
            TerraformModuleTarget,
            TerraformBackendTarget,
            TerraformVarFileTarget,
            TerraformDeploymentTarget,
        ],
        rules=[
            *tfsec_rules(),
            *tool.rules(),
            *source_files.rules(),
            QueryRule(LintResult, (TfSecRequest.Batch,)),
        ],
    )

    rule_runner.set_options(
        [
            "--terraform-tfsec-args='--no-colour'",
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
