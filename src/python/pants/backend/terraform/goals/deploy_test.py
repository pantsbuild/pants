# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json

import pytest

from pants.backend.terraform.goals.deploy import DeployTerraformFieldSet
from pants.backend.terraform.testutil import rule_runner_with_auto_approve, standard_deployment
from pants.core.goals.deploy import Deploy, DeployProcess
from pants.engine.internals.native_engine import Address
from pants.testutil.rule_runner import RuleRunner, mock_console

rule_runner = rule_runner_with_auto_approve
standard_deployment = standard_deployment


def test_run_terraform_deploy(rule_runner: RuleRunner, standard_deployment, tmpdir) -> None:
    """Test end-to-end running of a deployment."""
    rule_runner.write_files(standard_deployment.files)
    with mock_console(rule_runner.options_bootstrapper, stdin_content="yes") as (_, m):
        result = rule_runner.run_goal_rule(
            Deploy, args=["src/tf:stg", *rule_runner.options_bootstrapper.args]
        )

    # assert Pants thinks we succeeded
    assert result.stdout.splitlines() == []
    assert "✓ src/tf:stg deployed" in result.stderr.splitlines()

    # assert Terraform did things
    with open(standard_deployment.state_file) as raw_state_file:
        raw_state = raw_state_file.read()
    assert raw_state, "Terraform state file not found where expected."
    state = json.loads(raw_state)
    assert len(state["resources"]) == 1, "Resource not found in terraform state"


def test_deploy_terraform_forwards_args(rule_runner: RuleRunner, standard_deployment) -> None:
    rule_runner.write_files(standard_deployment.files)

    target = rule_runner.get_target(Address("src/tf", target_name="stg"))
    field_set = DeployTerraformFieldSet.create(target)
    deploy_process = rule_runner.request(DeployProcess, [field_set])
    assert deploy_process.process

    argv = deploy_process.process.process.argv

    assert "-chdir=src/tf" in argv, "Did not find expected -chdir"
    assert "-var-file=stg.tfvars" in argv, "Did not find expected -var-file"
    assert "-auto-approve" in argv, "Did not find expected passthrough args"


@pytest.mark.parametrize(
    "options,action,not_action",
    [
        ([], "apply", "plan"),
        (["--experimental-deploy-dry-run=False"], "apply", "plan"),
        (["--experimental-deploy-dry-run"], "plan", "apply"),
    ],
)
def test_deploy_terraform_adheres_to_dry_run_flag(
    rule_runner: RuleRunner, standard_deployment, options: list[str], action: str, not_action: str
) -> None:
    rule_runner.write_files(standard_deployment.files)
    rule_runner.set_options(options)

    target = rule_runner.get_target(Address("src/tf", target_name="stg"))
    field_set = DeployTerraformFieldSet.create(target)
    deploy_process = rule_runner.request(DeployProcess, [field_set])
    argv = deploy_process.process.process.argv

    assert action in argv, f"Expected {action} in argv"
    assert not_action not in argv, f"Did not expect {not_action} in argv"


def test_deploy_terraform_with_module(rule_runner: RuleRunner) -> None:
    """Test that we can deploy a root module with a nearby shared module."""
    files = {
        "src/tf/root/BUILD": """terraform_deployment(root_module=":mod")\nterraform_module(name="mod")""",
        "src/tf/root/main.tf": """module "mod0" { source = "../mod0" }""",
        "src/tf/mod0/BUILD": """terraform_module()""",
        "src/tf/mod0/main.tf": """resource "null_resource" "dep" {}""",
    }
    rule_runner.write_files(files)

    with mock_console(rule_runner.options_bootstrapper, stdin_content="yes") as (_, m):
        result = rule_runner.run_goal_rule(
            Deploy, args=["src/tf::", *rule_runner.options_bootstrapper.args]
        )

    # assert Pants thinks we succeeded
    assert result.stdout.splitlines() == []

    # assert deployment succeeded
    assert "✓ src/tf/root:root deployed" in result.stderr.splitlines()
    # assert module was not deployed
    assert not any("src/tf/mod0" in line for line in result.stderr.splitlines())
