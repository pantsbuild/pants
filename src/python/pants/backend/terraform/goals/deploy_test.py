# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from pathlib import Path

import pytest

from pants.backend.terraform import dependencies, dependency_inference, tool
from pants.backend.terraform.dependencies import InitialisedTerraform, TerraformInitRequest
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
            QueryRule(InitialisedTerraform, (TerraformInitRequest,)),
        ],
        preserve_tmpdirs=True,
    )
    return rule_runner


@dataclass
class StandardDeployment:
    files: dict[str, str]
    state_file: Path


@pytest.fixture
def standard_deployment(tmpdir) -> StandardDeployment:
    # We have to forward "--auto-approve" to TF because `mock_console` is noninteractive
    state_file = Path(str(tmpdir.mkdir(".terraform").join("state.json")))
    return StandardDeployment(
        {
            "src/tf/BUILD": """terraform_deployment(name="stg", var_files=["stg.tfvars"],extra_args=["--auto-approve"],backend_config="stg.tfbackend")""",
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
    with mock_console(rule_runner.options_bootstrapper, stdin_content="yes"):
        result = rule_runner.run_goal_rule(Deploy, args=["src/tf:stg"])

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
    assert "--auto-approve" in argv, "Did not find expected extra_args"
    # assert standard_deployment.state_file.check()
