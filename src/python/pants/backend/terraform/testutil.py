# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent  # noqa: PNT20

import pytest

from pants.backend.terraform import dependencies, dependency_inference, tool
from pants.backend.terraform.dependencies import TerraformInitRequest, TerraformInitResponse
from pants.backend.terraform.goals.deploy import DeployTerraformFieldSet
from pants.backend.terraform.goals.deploy import rules as terraform_deploy_rules
from pants.backend.terraform.target_types import TerraformDeploymentTarget, TerraformModuleTarget
from pants.core.goals import deploy
from pants.core.goals.deploy import DeployProcess
from pants.core.register import rules as core_rules
from pants.core.util_rules import source_files
from pants.engine import process
from pants.engine.internals.native_engine import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner_with_auto_approve() -> RuleRunner:
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
            "src/tf/BUILD": dedent(
                """
                terraform_deployment(
                    name="stg",
                    var_files=["stg.tfvars"],
                    backend_config="stg.tfbackend",
                    root_module=":mod",
                )
                terraform_module(name="mod")
            """
            ),
            "src/tf/main.tf": dedent(
                """
                terraform {
                    backend "local" {
                        path = "/tmp/will/not/exist"
                    }
                    required_providers {
                        null = {
                          source = "hashicorp/null"
                          version = "~>3.2.0" # there are later versions, so we can lock it to this version to check lockfile use
                        }
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
