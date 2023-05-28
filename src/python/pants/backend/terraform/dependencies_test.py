# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from pathlib import Path
from typing import Optional

from pants.backend.terraform.dependencies import InitialisedTerraform, TerraformInitRequest
from pants.backend.terraform.goals.deploy import DeployTerraformFieldSet
from pants.backend.terraform.goals.deploy_test import (
    StandardDeployment,
    rule_runner,
    standard_deployment,
)
from pants.engine.fs import DigestContents, FileContent
from pants.engine.internals.native_engine import Address
from pants.testutil.rule_runner import RuleRunner

rule_runner = rule_runner
standard_deployment = standard_deployment


def _do_init_terraform(
    rule_runner, standard_deployment, initialise_backend: bool
) -> DigestContents:
    rule_runner.write_files(standard_deployment.files)
    target = rule_runner.get_target(Address("src/tf", target_name="stg"))
    field_set = DeployTerraformFieldSet.create(target)
    result = rule_runner.request(
        InitialisedTerraform,
        [
            TerraformInitRequest(
                (field_set.sources,),
                field_set.backend_config,
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

    # Assert lockfile is included
    assert find_file(initialised_files, ".terraform.lock.hcl"), "Did not find expected provider"


def test_init_terraform_without_backends(
    rule_runner: RuleRunner, standard_deployment: StandardDeployment
) -> None:
    initialised_files = _do_init_terraform(
        rule_runner, standard_deployment, initialise_backend=False
    )

    # Not initialising the backend means that ./.terraform/.terraform.tfstate will not be present
    assert not find_file(
        initialised_files, "**/*.tfstate"
    ), "Terraform state file should not be present if the the request was to not initialise the backend"

    # The dependencies should still be present
    assert find_file(
        initialised_files,
        ".terraform/providers/registry.terraform.io/hashicorp/null/*/*/terraform-provider-null*",
    ), "Did not find expected provider"
