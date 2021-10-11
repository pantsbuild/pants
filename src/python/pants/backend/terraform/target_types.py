# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.rules import collect_rules
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    FieldSet,
    MultipleSourcesField,
    Target,
)


class TerraformModuleSourcesField(MultipleSourcesField):
    default = ("*.tf",)
    expected_file_extensions = (".tf",)


@dataclass(frozen=True)
class TerraformFieldSet(FieldSet):
    required_fields = (TerraformModuleSourcesField,)

    sources: TerraformModuleSourcesField


class TerraformModuleTarget(Target):
    alias = "terraform_module"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, TerraformModuleSourcesField)
    help = (
        "A single Terraform module corresponding to a directory.\n\n"
        "There must only be one `terraform_module` in a directory.\n\n"
        "Use `terraform_modules` to generate `terraform_module` targets for less boilerplate."
    )


class TerraformModulesGeneratingSourcesField(MultipleSourcesField):
    # TODO: This currently only globs .tf files but not non-.tf files referenced by Terraform config. This
    # should be updated to allow for the generated TerraformModule targets to capture all files in the diectory
    # other than BUILD files.
    default = ("**/*.tf",)
    expected_file_extensions = (".tf",)


class TerraformModulesGeneratorTarget(Target):
    alias = "terraform_modules"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, TerraformModulesGeneratingSourcesField)
    help = (
        "Generate a `terraform_module` target for each directory from the `sources` field "
        "where Terraform files are present."
    )


def rules():
    return collect_rules()
