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
            TerraformBackendTarget,
            TerraformVarFileTarget,
            TerraformDeploymentTarget,
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
                    var_files=[":stg_vars"],
                    backend_config=":stg_tfbackend",
                    root_module=":mod",
                )
                terraform_backend(name="stg_tfbackend", source="stg.tfbackend")
                terraform_var_files(name="stg_vars", sources=["stg.tfvars"])
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


terraform_lockfile = """\
provider "registry.terraform.io/hashicorp/null" {
  version     = "3.2.0"
  constraints = "~> 3.2.0"
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

# TODO: pin upper bound so this doesn't break with a new release of the provider
terraform_lockfile_regenerated = """\
# This file is maintained automatically by "terraform init".
# Manual edits may be lost in future updates.

provider "registry.terraform.io/hashicorp/null" {
  version     = "3.2.1"
  constraints = "~> 3.2.0"
  hashes = [
    "h1:FbGfc+muBsC17Ohy5g806iuI1hQc4SIexpYCrQHQd8w=",
    "zh:58ed64389620cc7b82f01332e27723856422820cfd302e304b5f6c3436fb9840",
    "zh:62a5cc82c3b2ddef7ef3a6f2fedb7b9b3deff4ab7b414938b08e51d6e8be87cb",
    "zh:63cff4de03af983175a7e37e52d4bd89d990be256b16b5c7f919aff5ad485aa5",
    "zh:74cb22c6700e48486b7cabefa10b33b801dfcab56f1a6ac9b6624531f3d36ea3",
    "zh:78d5eefdd9e494defcb3c68d282b8f96630502cac21d1ea161f53cfe9bb483b3",
    "zh:79e553aff77f1cfa9012a2218b8238dd672ea5e1b2924775ac9ac24d2a75c238",
    "zh:a1e06ddda0b5ac48f7e7c7d59e1ab5a4073bbcf876c73c0299e4610ed53859dc",
    "zh:c37a97090f1a82222925d45d84483b2aa702ef7ab66532af6cbcfb567818b970",
    "zh:e4453fbebf90c53ca3323a92e7ca0f9961427d2f0ce0d2b65523cc04d5d999c2",
    "zh:e80a746921946d8b6761e77305b752ad188da60688cfd2059322875d363be5f5",
    "zh:fbdb892d9822ed0e4cb60f2fedbdbb556e4da0d88d3b942ae963ed6ff091e48f",
    "zh:fca01a623d90d0cad0843102f9b8b9fe0d3ff8244593bd817f126582b52dd694",
  ]
}
"""
