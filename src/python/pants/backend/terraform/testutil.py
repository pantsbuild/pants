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
from pants.backend.terraform.goals.lockfiles import rules as terraform_lockfile_rules
from pants.backend.terraform.target_types import (
    TerraformBackendTarget,
    TerraformDeploymentTarget,
    TerraformLockfileTarget,
    TerraformModuleTarget,
    TerraformVarFileTarget,
)
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
        target_types=[
            TerraformModuleTarget,
            TerraformDeploymentTarget,
            TerraformBackendTarget,
            TerraformVarFileTarget,
            TerraformLockfileTarget,
        ],
        rules=[
            *dependency_inference.rules(),
            *dependencies.rules(),
            *tool.rules(),
            *terraform_deploy_rules(),
            *terraform_lockfile_rules(),
            *source_files.rules(),
            *deploy.rules(),
            *core_rules(),
            *process.rules(),
            QueryRule(DeployProcess, (DeployTerraformFieldSet,)),
            QueryRule(TerraformInitResponse, (TerraformInitRequest,)),
        ],
        preserve_tmpdirs=True,
    )
    # We have to forward "--auto-approve" to TF because `mock_console` is noninteractive
    rule_runner.set_options(["--download-terraform-args='-auto-approve'"])
    return rule_runner


@dataclass
class StandardDeployment:
    files: dict[str, str]
    state_file: Path
    target: Address = Address("src/tf", target_name="stg")


@pytest.fixture
def standard_deployment(tmpdir) -> StandardDeployment:
    state_file = Path(str(tmpdir.mkdir(".terraform").join("state.json")))
    return StandardDeployment(
        {
            "src/tf/BUILD": dedent(
                """
                terraform_deployment(
                    name="stg",
                    root_module=":mod",
                    dependencies=[":stg.tfvars", ":stg.tfbackend"],
                )
                terraform_backend(name="stg.tfbackend", source="stg.tfbackend")
                terraform_var_files(name="stg.tfvars")
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
                          version = "~> 3.2.0, <= 3.2.2"
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


terraform_lockfile = """\
provider "registry.terraform.io/hashicorp/null" {
  version     = "3.2.0"
  constraints = "~> 3.2.0, <= 3.2.2"
  hashes = [
    "h1:pfjuwssoCoBDRbutlVLAP8wiDrkQ3G4d3rs+f7uSh2A=",
    "zh:1d88ea3af09dcf91ad0aaa0d3978ca8dcb49dc866c8615202b738d73395af6b5",
    "zh:3844db77bfac2aca43aaa46f3f698c8e5320a47e838ee1318408663449547e7e",
    "zh:538fadbd87c576a332b7524f352e6004f94c27afdd3b5d105820d328dc49c5e3",
    "zh:56def6f00fc2bc9c3c265b841ce71e80b77e319de7b0f662425b8e5e7eb26846",
    "zh:78d5eefdd9e494defcb3c68d282b8f96630502cac21d1ea161f53cfe9bb483b3",
    "zh:8fce56e5f1d13041d8047a1d0c93f930509704813a28f8d39c2b2082d7eebf9f",
    "zh:989e909a5eca96b8bdd4a0e8609f1bd525949fd226ae870acedf2da0c55b0451",
    "zh:99ddc34ad13e04e9c3477f5422fbec20fc13395ff940720c287bfa5c546d2fbc",
    "zh:b546666da4b4b60c0eec23faab7f94dc900e48f66b5436fc1ac0b87c6709ef04",
    "zh:d56643cb08cba6e074d70c4af37d5de2bd7c505f81d866d6d47c9e1d28ec65d1",
    "zh:f39ac5ff9e9d00e6a670bce6825529eded4b0b4966abba36a387db5f0712d7ba",
    "zh:fe102389facd09776502327352be99becc1ac09e80bc287db84a268172be641f",
  ]
}"""

terraform_lockfile_regenerated = """\
# This file is maintained automatically by "terraform init".
# Manual edits may be lost in future updates.

provider "registry.terraform.io/hashicorp/null" {
  version     = "3.2.2"
  constraints = "~> 3.2.0, <= 3.2.2"
  hashes = [
    "h1:Gef5VGfobY5uokA5nV/zFvWeMNR2Pmq79DH94QnNZPM=",
    "h1:zT1ZbegaAYHwQa+QwIFugArWikRJI9dqohj8xb0GY88=",
    "zh:3248aae6a2198f3ec8394218d05bd5e42be59f43a3a7c0b71c66ec0df08b69e7",
    "zh:32b1aaa1c3013d33c245493f4a65465eab9436b454d250102729321a44c8ab9a",
    "zh:38eff7e470acb48f66380a73a5c7cdd76cc9b9c9ba9a7249c7991488abe22fe3",
    "zh:4c2f1faee67af104f5f9e711c4574ff4d298afaa8a420680b0cb55d7bbc65606",
    "zh:544b33b757c0b954dbb87db83a5ad921edd61f02f1dc86c6186a5ea86465b546",
    "zh:696cf785090e1e8cf1587499516b0494f47413b43cb99877ad97f5d0de3dc539",
    "zh:6e301f34757b5d265ae44467d95306d61bef5e41930be1365f5a8dcf80f59452",
    "zh:78d5eefdd9e494defcb3c68d282b8f96630502cac21d1ea161f53cfe9bb483b3",
    "zh:913a929070c819e59e94bb37a2a253c228f83921136ff4a7aa1a178c7cce5422",
    "zh:aa9015926cd152425dbf86d1abdbc74bfe0e1ba3d26b3db35051d7b9ca9f72ae",
    "zh:bb04798b016e1e1d49bcc76d62c53b56c88c63d6f2dfe38821afef17c416a0e1",
    "zh:c23084e1b23577de22603cff752e59128d83cfecc2e6819edadd8cf7a10af11e",
  ]
}
"""
