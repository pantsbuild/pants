# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.engine.rules import collect_rules
from pants.engine.target import COMMON_TARGET_FIELDS, Dependencies, Sources, Target


class TerraformSources(Sources):
    expected_file_extensions = (".tf",)


class TerraformModuleSources(TerraformSources):
    default = ("*.tf",)


class TerraformModule(Target):
    alias = "terraform_module"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, TerraformModuleSources)
    help = """A single Terraform module."""


class TerraformModulesSources(TerraformSources):
    # TODO: This currently only globs .tf files but not non-.tf files referenced by Terraform config. This
    # should be updated to allow for the generated TerraformModule targets to capture all files in the diectory
    # other than BUILD files.
    default = ("**/*.tf",)


class TerraformModules(Target):
    alias = "terraform_modules"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, TerraformModulesSources)
    help = (
        "Generate a `terraform_module` target for each directory from the `sources` field "
        "where Terraform files are present."
    )


def rules():
    return collect_rules()
