# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from pants.backend.terraform import dependencies, dependency_inference, tool
from pants.backend.terraform.dependencies import TerraformInitRequest, TerraformInitResponse
from pants.backend.terraform.goals.deploy import DeployTerraformFieldSet
from pants.backend.terraform.goals.deploy import rules as terraform_deploy_rules
from pants.backend.terraform.target_types import TerraformDeploymentTarget, TerraformModuleTarget
from pants.core.goals import deploy
from pants.core.goals.deploy import Deploy, DeployProcess
from pants.core.register import rules as core_rules
from pants.core.util_rules import source_files
from pants.engine import process
from pants.engine.internals.native_engine import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner, mock_console


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[TerraformModuleTarget, TerraformDeploymentTarget],
        rules=[
            *dependency_inference.rules(),
            *dependencies.rules(),
            *tool.rules(),
            *terraform_deploy_rules(),
            *source_files.rules(),
            *deploy.rules(),
            *core_rules(),
            *process.rules(),
            QueryRule(DeployProcess, (DeployTerraformFieldSet,)),
            QueryRule(TerraformInitResponse, (TerraformInitRequest,)),
        ],
        preserve_tmpdirs=True,
    )
    rule_runner.set_options(["--download-terraform-args='-auto-approve'"])
    return rule_runner


@dataclass
class StandardDeployment:
    files: dict[str, str]
    state_file: Path
    target: Address = Address("src/tf", target_name="stg")


@pytest.fixture
def standard_deployment(tmpdir) -> StandardDeployment:
    # We have to forward "--auto-approve" to TF because `mock_console` is noninteractive
    state_file = Path(str(tmpdir.mkdir(".terraform").join("state.json")))
    return StandardDeployment(
        {
            "src/tf/BUILD": textwrap.dedent(
                """\
                terraform_deployment(
                    name="stg",
                    var_files=["stg.tfvars"],
                    backend_config="stg.tfbackend",
                    root_module=":mod",
                )
                terraform_module(name="mod")
            """
            ),
            "src/tf/main.tf": textwrap.dedent(
                """\
                terraform {
                    backend "local" {
                        path = "/tmp/will/not/exist"
                    }
                }
                variable "var0" {}
                resource "null_resource" "dep" {}
                """
            ),
            "src/tf/stg.tfvars": "var0=0",
            "src/tf/stg.tfbackend": f'path="{state_file}"',
        },
        state_file,
    )


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
    # assert standard_deployment.state_file.check()


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
