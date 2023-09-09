# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import json
import textwrap
from pathlib import Path
from typing import Optional

from pants.backend.terraform.dependencies import TerraformInitRequest, TerraformInitResponse
from pants.backend.terraform.goals.deploy import DeployTerraformFieldSet
from pants.backend.terraform.testutil import (
    StandardDeployment,
    rule_runner_with_auto_approve,
    standard_deployment,
)
from pants.engine.fs import DigestContents, FileContent
from pants.engine.internals.native_engine import Address
from pants.testutil.rule_runner import RuleRunner

rule_runner = rule_runner_with_auto_approve
standard_deployment = standard_deployment


def _do_init_terraform(
    rule_runner: RuleRunner, standard_deployment: StandardDeployment, initialise_backend: bool
) -> DigestContents:
    rule_runner.write_files(standard_deployment.files)
    target = rule_runner.get_target(standard_deployment.target)
    field_set = DeployTerraformFieldSet.create(target)
    result = rule_runner.request(
        TerraformInitResponse,
        [
            TerraformInitRequest(
                field_set.root_module,
                field_set.backend_config,
                field_set.dependencies,
                initialise_backend=initialise_backend,
            )
        ],
    )
    initialised_files = rule_runner.request(DigestContents, [result.sources_and_deps])
    assert isinstance(initialised_files, DigestContents)
    return initialised_files


def find_file(files: DigestContents, pattern: str) -> Optional[FileContent]:
    return next((file for file in files if Path(file.path).match(pattern)), None)


def test_init_terraform(rule_runner: RuleRunner, standard_deployment: StandardDeployment) -> None:
    """Test for the happy path of initialising Terraform with a backend config."""
    initialised_files = _do_init_terraform(
        rule_runner, standard_deployment, initialise_backend=True
    )

    # Assert uses backend by checking that the overrides in the backend file are present in the local stub state file
    stub_tfstate_raw = find_file(initialised_files, "src/tf/.terraform/terraform.tfstate")
    assert stub_tfstate_raw
    stub_tfstate = json.loads(stub_tfstate_raw.content)
    assert stub_tfstate["backend"]["config"]["path"] == str(standard_deployment.state_file)

    # Assert dependencies are initialised by checking for the dependency itself
    assert find_file(
        initialised_files,
        ".terraform/providers/registry.terraform.io/hashicorp/null/*/*/terraform-provider-null*",
    ), "Did not find expected provider"

    # Assert lockfile is generated and included
    assert find_file(initialised_files, ".terraform.lock.hcl"), "Did not find expected provider"


def test_init_terraform_uses_lockfiles(
    rule_runner: RuleRunner, standard_deployment: StandardDeployment
) -> None:
    """Test that we can use generated lockfiles."""
    requested_version = "3.2.0"

    terraform_lockfile = textwrap.dedent(
        f"""\
        provider "registry.terraform.io/hashicorp/null" {{
          version     = "3.2.0"
          constraints = "~> {requested_version}"
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
        }}"""
    )

    deployment_with_lockfile = dataclasses.replace(
        standard_deployment,
        files={**standard_deployment.files, **{"src/tf/.terraform.lock.hcl": terraform_lockfile}},
    )

    initialised_files = _do_init_terraform(
        rule_runner, deployment_with_lockfile, initialise_backend=True
    )

    # Assert lockfile is not regenerated
    result_lockfile = find_file(initialised_files, ".terraform.lock.hcl")
    assert result_lockfile, "Did not find lockfile"
    assert (
        f'version     = "{requested_version}"' in result_lockfile.content.decode()
    ), "version in lockfile has changed, we should not have regenerated the lockfile"

    # Assert dependencies are initialised to the older version
    result_provider = find_file(
        initialised_files,
        ".terraform/providers/registry.terraform.io/hashicorp/null/*/*/terraform-provider-null*",
    )
    assert result_provider, "Did not find any providers, did we initialise them successfully?"
    assert (
        requested_version in result_provider.path
    ), "initialised provider did not have our requested version, did the lockfile show up and did we regenerate it?"


def test_init_terraform_without_backends(
    rule_runner: RuleRunner, standard_deployment: StandardDeployment
) -> None:
    initialised_files = _do_init_terraform(
        rule_runner, standard_deployment, initialise_backend=False
    )

    # Not initialising the backend means that ./.terraform/.terraform.tfstate will not be present
    assert not find_file(
        initialised_files, "**/*.tfstate"
    ), "Terraform state file should not be present if the request was to not initialise the backend"

    # The dependencies should still be present
    assert find_file(
        initialised_files,
        ".terraform/providers/registry.terraform.io/hashicorp/null/*/*/terraform-provider-null*",
    ), "Did not find expected provider"


def test_init_terraform_with_in_repo_module(rule_runner: RuleRunner, tmpdir) -> None:
    deployment_files = {
        "src/tf/deployment/BUILD": textwrap.dedent(
            """\
            terraform_deployment(name="root", root_module=":mod")
            terraform_module(name="mod")
        """
        ),
        "src/tf/deployment/main.tf": textwrap.dedent(
            """\
            module "mod0" {
              source = "../module/"
            }
        """
        ),
    }
    module_files = {
        "src/tf/module/BUILD": "terraform_module()",
        "src/tf/module/main.tf": 'resource "null_resource" "dep" {}',
    }

    deployment = StandardDeployment(
        {**deployment_files, **module_files},
        Path(str(tmpdir.mkdir(".terraform").join("state.json"))),
        Address("src/tf/deployment", target_name="root"),
    )
    initialised_files = _do_init_terraform(rule_runner, deployment, initialise_backend=True)

    # Assert that our module got included in the module.json
    assert initialised_files
    modules_file_raw = find_file(initialised_files, ".terraform/modules/modules.json")
    assert modules_file_raw
    modules_file = json.loads(modules_file_raw.content)
    assert any(
        module for module in modules_file["Modules"] if module["Key"] == "mod0"
    ), "Did not find our module in modules.json"

    # Assert that the module was explored as part of init
    assert find_file(
        initialised_files,
        ".terraform/providers/registry.terraform.io/hashicorp/null/*/*/terraform-provider-null*",
    ), "Did not find expected provider contained in module, did we successfully include it in the files passed to `init`?"
