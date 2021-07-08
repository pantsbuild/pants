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


def rules():
    return collect_rules()
