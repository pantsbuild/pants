# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap
from typing import Dict, Sequence

import pytest

from pants.backend.terraform import dependencies, dependency_inference, tool
from pants.backend.terraform.goals import check
from pants.backend.terraform.goals.check import TerraformCheckRequest
from pants.backend.terraform.target_types import (
    TerraformDeploymentFieldSet,
    TerraformDeploymentTarget,
    TerraformModuleTarget,
)
from pants.core.goals.check import CheckResult, CheckResults
from pants.core.util_rules import external_tool, source_files
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent
from pants.engine.target import Target
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[TerraformModuleTarget, TerraformDeploymentTarget],
        rules=[
            *external_tool.rules(),
            *check.rules(),
            *tool.rules(),
            *source_files.rules(),
            *dependencies.rules(),
            *dependency_inference.rules(),
            QueryRule(CheckResults, (TerraformCheckRequest,)),
            QueryRule(SourceFiles, (SourceFilesRequest,)),
        ],
    )


GOOD_SOURCE = FileContent(
    "good.tf",
    textwrap.dedent(
        """
        locals {
          good_base = "xyzzy"
          foo       = "${local.good_base}"
        }
        """
    ).encode("utf-8"),
)

# The invalid part is the use of interpolation solely for a variable.
BAD_SOURCE = FileContent(
    "bad.tf",
    textwrap.dedent(
        """
        locals {
          bad_base = "xyzzy"
          bar = "${bad_base}"
        }
        """
    ).encode("utf-8"),
)

# This resource uses the null_resource provider. Terraform will need to run `init` to init the provider
SOURCE_WITH_PROVIDER = FileContent(
    "provided.tf",
    textwrap.dedent(
        """
        resource "null_resource" "dep" {}
        """
    ).encode("utf-8"),
)


def make_target(
    rule_runner: RuleRunner, source_files: list[FileContent], *, target_name="target"
) -> Target:
    files = {
        "BUILD": f"terraform_module(name='{target_name}mod')\nterraform_deployment(name='{target_name}', root_module=':{target_name}mod')\n",
    }
    files.update({source_file.path: source_file.content.decode() for source_file in source_files})
    rule_runner.write_files(files)
    return rule_runner.get_target(Address("", target_name=target_name))


def run_terraform_validate(
    rule_runner: RuleRunner,
    targets: list[Target],
    *,
    args: list[str] | None = None,
) -> Sequence[CheckResult]:
    rule_runner.set_options(args or ())
    field_sets = [TerraformDeploymentFieldSet.create(tgt) for tgt in targets]
    check_results = rule_runner.request(CheckResults, [TerraformCheckRequest(field_sets)])
    return check_results.results


def get_content(rule_runner: RuleRunner, digest: Digest) -> DigestContents:
    return rule_runner.request(DigestContents, [digest])


def get_digest(rule_runner: RuleRunner, source_files: list[FileContent]) -> Digest:
    return rule_runner.request(Digest, [CreateDigest(source_files)])


def test_passing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE])
    check_results = run_terraform_validate(rule_runner, [target])
    assert len(check_results) == 1
    assert check_results[0].exit_code == 0
    assert check_results[0].stderr == ""


def test_failing_source(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    check_results = run_terraform_validate(rule_runner, [target])
    assert len(check_results) == 1
    assert check_results[0].exit_code == 1
    assert "bad.tf" in check_results[0].stderr


def test_mixed_sources(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [GOOD_SOURCE, BAD_SOURCE])
    check_results = run_terraform_validate(rule_runner, [target])
    assert len(check_results) == 1
    assert check_results[0].exit_code == 1
    assert "bad.tf" in check_results[0].stderr
    assert "good.tf" not in check_results[0].stderr


def test_multiple_targets(rule_runner: RuleRunner) -> None:
    source_files = [
        FileContent(
            "BUILD",
            textwrap.dedent(
                """\
                terraform_module(name="good", sources=["good.tf"])
                terraform_deployment(name="tgt_good", root_module=":good")
                terraform_module(name="bad", sources=["bad.tf"])
                terraform_deployment(name="tgt_bad", root_module=":bad")
            """
            ).encode("utf-8"),
        ),
        BAD_SOURCE,
        GOOD_SOURCE,
    ]

    rule_runner.write_files(
        {source_file.path: source_file.content.decode() for source_file in source_files}
    )

    targets = [
        rule_runner.get_target(Address("", target_name="tgt_good")),
        rule_runner.get_target(Address("", target_name="tgt_bad")),
    ]

    check_results = run_terraform_validate(rule_runner, targets)
    assert len(check_results) == 2
    for check_result in check_results:
        assert check_result.partition_description
        if "bad" in check_result.partition_description:
            assert check_result.exit_code == 1
        elif "good" in check_result.partition_description:
            assert check_result.exit_code == 0
        else:
            raise AssertionError(f"Did not find expected target in check result {check_result}")


def test_skip(rule_runner: RuleRunner) -> None:
    target = make_target(rule_runner, [BAD_SOURCE])
    lint_results = run_terraform_validate(rule_runner, [target], args=["--terraform-validate-skip"])
    assert not lint_results


def test_with_dependency(rule_runner: RuleRunner) -> None:
    """Sources with a provider need to have `terraform init` run before to initialise the provider.

    Without `init`, `terraform validate` fails. It is therefore sufficient to just test that the
    process ran successfully
    """
    targets = [make_target(rule_runner, [SOURCE_WITH_PROVIDER])]
    check_results = run_terraform_validate(rule_runner, targets)
    assert check_results[0].exit_code == 0


def test_in_folder(rule_runner: RuleRunner) -> None:
    """Test that we can `check` terraform files not in the root folder."""
    target_name = "in_folder"
    files = {
        "folder/BUILD": textwrap.dedent(
            f"""\
            terraform_deployment(name='{target_name}', root_module=':mod0')
            terraform_module(name='mod0')
            """
        ),
        "folder/provided.tf": textwrap.dedent(
            """
            resource "null_resource" "dep" {}
            resource "random_pet" "random" {}
            """
        ),
    }
    rule_runner.write_files(files)
    target = rule_runner.get_target(Address("folder", target_name=target_name))

    check_results = run_terraform_validate(rule_runner, [target])
    assert check_results[0].exit_code == 0


def test_conflicting_provider_versions(rule_runner: RuleRunner) -> None:
    """Test that 2 separate terraform_modules can request conflicting providers.

    I think this test is really only necessary because we don't really separate the files we pass.
    If a large target glob is used (`::`), we get all the sources
    """
    target_name = "in_folder"
    versions = ["3.2.1", "3.0.0"]

    def make_terraform_module(version: str) -> Dict[str, str]:
        return {
            f"folder{version}/BUILD": textwrap.dedent(
                f"""\
                terraform_deployment(name='{target_name}', root_module=':mod')
                terraform_module(name='mod')
            """
            ),
            f"folder{version}/provided.tf": textwrap.dedent(
                """
            terraform {
              required_providers {
                null = {
                  source = "hashicorp/null"
                  version = "%s"
                }
              }
            }
            resource "null_resource" "res" {}
            """
                % version
            ),
        }

    files = {}
    for version in versions:
        files.update(make_terraform_module(version))

    rule_runner.write_files(files)
    targets = [
        rule_runner.get_target(Address(folder, target_name=target_name))
        for folder in (f"folder{version}" for version in versions)
    ]

    check_results = run_terraform_validate(rule_runner, targets)
    assert len(check_results) == len(versions)
    assert all(check_result.exit_code == 0 for check_result in check_results)
