# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

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
    terraform_lockfile,
)
from pants.engine.fs import DigestContents, DigestEntries, FileContent, SymlinkEntry
from pants.engine.internals.native_engine import Address
from pants.testutil.rule_runner import RuleRunner

rule_runner = rule_runner_with_auto_approve
standard_deployment = standard_deployment


def _do_init_terraform(
    rule_runner: RuleRunner, standard_deployment: StandardDeployment, initialise_backend: bool
) -> tuple[DigestContents, DigestEntries]:
    rule_runner.write_files(standard_deployment.files)
    target = rule_runner.get_target(standard_deployment.target)
    field_set = DeployTerraformFieldSet.create(target)
    result = rule_runner.request(
        TerraformInitResponse,
        [
            TerraformInitRequest(
                field_set.root_module,
                field_set.dependencies,
                initialise_backend=initialise_backend,
            )
        ],
    )
    initialised_files = rule_runner.request(DigestContents, [result.sources_and_deps])
    initialised_entries = rule_runner.request(DigestEntries, [result.sources_and_deps])
    assert isinstance(initialised_files, DigestContents)
    return initialised_files, initialised_entries


def find_file(files: DigestContents, pattern: str) -> Optional[FileContent]:
    return next((file for file in files if Path(file.path).match(pattern)), None)


def find_link(entries: DigestEntries, pattern: str) -> Optional[SymlinkEntry]:
    for entry in entries:
        if not isinstance(entry, SymlinkEntry):
            continue

        if Path(entry.path).match(pattern):
            # allow any prefix to account for absolute targets
            return entry

    return None


def test_init_terraform(rule_runner: RuleRunner, standard_deployment: StandardDeployment) -> None:
    """Test for the happy path of initialising Terraform with a backend config."""
    initialised_files, initialised_links = _do_init_terraform(
        rule_runner, standard_deployment, initialise_backend=True
    )

    # Assert uses backend by checking that the overrides in the backend file are present in the local stub state file
    stub_tfstate_raw = find_file(initialised_files, "src/tf/.terraform/terraform.tfstate")
    assert stub_tfstate_raw
    stub_tfstate = json.loads(stub_tfstate_raw.content)
    assert stub_tfstate["backend"]["config"]["path"] == str(standard_deployment.state_file)

    # Assert dependencies are initialised by checking for the dependency itself
    assert find_link(
        initialised_links,
        ".terraform/providers/registry.terraform.io/hashicorp/null/*/*",
    ), "Did not find expected provider"

    # Assert lockfile is included
    assert find_file(initialised_files, ".terraform.lock.hcl"), "Did not find expected provider"


def test_init_terraform_uses_lockfiles(
    rule_runner: RuleRunner, standard_deployment: StandardDeployment
) -> None:
    """Test that we can use generated lockfiles."""
    requested_version = "3.2.0"

    deployment_with_lockfile = dataclasses.replace(
        standard_deployment,
        files={**standard_deployment.files, **{"src/tf/.terraform.lock.hcl": terraform_lockfile}},
    )

    initialised_files, initialised_entries = _do_init_terraform(
        rule_runner, deployment_with_lockfile, initialise_backend=True
    )

    # Assert lockfile is not regenerated
    result_lockfile = find_file(initialised_files, ".terraform.lock.hcl")
    assert result_lockfile, "Did not find lockfile"
    assert (
        f'version     = "{requested_version}"' in result_lockfile.content.decode()
    ), "version in lockfile has changed, we should not have regenerated the lockfile"

    # Assert dependencies are initialised to the older version
    result_provider = find_link(
        initialised_entries,
        ".terraform/providers/registry.terraform.io/hashicorp/null/*/*",
    )
    assert result_provider, "Did not find any providers, did we initialise them successfully?"
    assert (
        requested_version in result_provider.path
    ), "initialised provider did not have our requested version, did the lockfile show up and did we regenerate it?"


def test_init_terraform_without_backends(
    rule_runner: RuleRunner, standard_deployment: StandardDeployment
) -> None:
    initialised_files, initialised_entries = _do_init_terraform(
        rule_runner, standard_deployment, initialise_backend=False
    )

    # Not initialising the backend means that ./.terraform/.terraform.tfstate will not be present
    assert not find_file(
        initialised_files, "**/*.tfstate"
    ), "Terraform state file should not be present if the request was to not initialise the backend"

    # The dependencies should still be present
    assert find_link(
        initialised_entries,
        ".terraform/providers/registry.terraform.io/hashicorp/null/*/*",
    ), "Did not find expected provider"


def assert_init_module(modules, target_module_id: str, message: str) -> None:
    assert (
        target_module_id in modules
    ), f"{message}: Did not find {target_module_id} in modules.json. Found modules are {list(modules.items())}"


def test_init_terraform_with_transitive_module(rule_runner: RuleRunner, tmpdir) -> None:
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
        "src/tf/module/main.tf": 'module "transitive" { source = "../transitive/" }',
    }
    transitive_module_files = {
        "src/tf/transitive/BUILD": "terraform_module()",
        "src/tf/transitive/main.tf": 'resource "null_resource" "dep" {}',
    }

    deployment = StandardDeployment(
        {**deployment_files, **module_files, **transitive_module_files},
        Path(str(tmpdir.mkdir(".terraform").join("state.json"))),
        Address("src/tf/deployment", target_name="root"),
    )
    initialised_files, initialised_entries = _do_init_terraform(
        rule_runner, deployment, initialise_backend=True
    )

    assert initialised_files
    # Assert that init succeeded and created the modules mapping
    modules_file_raw = find_file(initialised_files, ".terraform/modules/modules.json")
    assert modules_file_raw

    modules_file = json.loads(modules_file_raw.content)
    modules = {module["Key"]: module for module in modules_file["Modules"]}

    assert_init_module(
        modules, "mod0", message="Assert that the deployment pulled in it root module"
    )
    assert_init_module(
        modules, "mod0.transitive", message="Assert that the root module pulled in its dependents"
    )

    # Assert that the provider dependency was initialised
    assert find_link(
        initialised_entries,
        ".terraform/providers/registry.terraform.io/hashicorp/null/*/*",
    ), "Did not find expected provider contained in module, did we successfully include it in the files passed to `init`?"
