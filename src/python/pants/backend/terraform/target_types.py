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
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import softwrap


class TerraformModuleSourcesField(MultipleSourcesField):
    default = ("*.tf",)
    expected_file_extensions = (".tf",)
    ban_subdirectories = True
    help = generate_multiple_sources_field_help_message(
        "Example: `sources=['example.tf', 'new_*.tf', '!old_ignore.tf']`"
    )


@dataclass(frozen=True)
class TerraformFieldSet(FieldSet):
    required_fields = (TerraformModuleSourcesField,)

    sources: TerraformModuleSourcesField


class TerraformModuleTarget(Target):
    alias = "terraform_module"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, TerraformModuleSourcesField)
    help = softwrap(
        """
        A single Terraform module corresponding to a directory.

        There must only be one `terraform_module` in a directory.

        Use `terraform_modules` to generate `terraform_module` targets for less boilerplate.
        """
    )


def rules():
    return collect_rules()
