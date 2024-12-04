from __future__ import annotations

import json

import pytest
from pants.backend.terraform.testutil import rule_runner_with_auto_approve, standard_deployment, \
    all_terraform_target_types, StandardDeployment

from pants.backend.terraform.target_types import TerraformDeploymentTarget, TerraformModuleTarget, \
    TerraformDeploymentFieldSet, TerraformFieldSet
from pants.backend.tools.trivy.testutil import trivy_config
from pants.core.goals.lint import LintResult
from pants.core.util_rules import source_files
from pants.core.util_rules.partitions import PartitionMetadata
from pants.engine.internals.native_engine import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.backend.terraform import dependencies, dependency_inference, tool

from pants.backend.terraform.lint.trivy.rules import rules as trivy_terraform_rules, TrivyLintTerraformRequest, \
    TrivyLintTerraformDeploymentRequest, TrivyLintTerraformModuleRequest
from pants.backend.tools.trivy.rules import rules as trivy_rules
from pants.backend.terraform import tool

standard_deployment = standard_deployment

@pytest.fixture
def rule_runner(standard_deployment: StandardDeployment) -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=all_terraform_target_types,
        rules = [
            *trivy_terraform_rules(),
            *tool.rules(),
            *trivy_rules(),
            *source_files.rules(),
            *dependencies.rules(),
            # *dependency_inference.rules(),
            QueryRule(LintResult, (TrivyLintTerraformDeploymentRequest.Batch,)),
            QueryRule(LintResult, (TrivyLintTerraformModuleRequest.Batch,)),
        ],
        bootstrap_args=["--keep-sandboxes=always"]
    )


    trivy_deployment = standard_deployment.with_added_files({
        "src/tf/bad.tf": bad_terraform,
        "src/tf/stg.tfvars": terraform_values,
        "trivy.yaml": trivy_config,
    })
    rule_runner.write_files(trivy_deployment.files)
    # # test changing severity
    # rule_runner.set_options([
    #     "--trivy-severity=CRITICAL"
    # ])


    return rule_runner


bad_terraform = """\
variable "encrypted" { type=bool }

resource "aws_instance" "this" {
  ami           = data.aws_ami.amazon_linux.id
  instance_type = "t3.nano"
  subnet_id     = element(module.vpc.private_subnets, 0)
  
  root_block_device {
    # The deployment sets this to `true` in the vars file to test that vars files are passed correctly
    encrypted = var.encrypted
  }
}
"""

terraform_values = """\
encrypted = true
"""


def test_lint_deployment(rule_runner) -> None:
    tgt = rule_runner.get_target(Address("src/tf", target_name="stg"))

    result = rule_runner.request(
        LintResult, [TrivyLintTerraformDeploymentRequest.Batch("trivy", (TerraformDeploymentFieldSet.create(tgt),), PartitionMetadata)])

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    misconfs_by_target = {res["Target"]: res for res in report["Results"]}
    assert "bad.tf" in misconfs_by_target, f"Did not find expected file in results, files={list(misconfs_by_target.keys())}"
    assert misconfs_by_target["bad.tf"]["MisconfSummary"]["Failures"] == 1, "Did not find expected number of misconfigurations"


def test_lint_module(rule_runner) -> None:
    tgt = rule_runner.get_target(Address("src/tf", target_name="mod"))

    result = rule_runner.request(
        LintResult, [TrivyLintTerraformModuleRequest.Batch("trivy", (TerraformFieldSet.create(tgt),), PartitionMetadata)])

    assert result.exit_code == 1
    report = json.loads(result.stdout)
    misconfs_by_target = {res["Target"]: res for res in report["Results"]}
    assert "bad.tf" in misconfs_by_target, f"Did not find expected file in results, files={list(misconfs_by_target.keys())}"
    assert misconfs_by_target["bad.tf"]["MisconfSummary"]["Failures"] == 2, "Did not find expected number of misconfigurations"
