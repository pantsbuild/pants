# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    Dependencies,
    DescriptionField,
    FieldSet,
    MultipleSourcesField,
    OptionalSingleSourceField,
    StringSequenceField,
    Target,
    Targets,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import help_text


class TerraformDependenciesField(Dependencies):
    pass


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
    dependencies: TerraformDependenciesField


class TerraformModuleTarget(Target):
    alias = "terraform_module"
    core_fields = (*COMMON_TARGET_FIELDS, TerraformDependenciesField, TerraformModuleSourcesField)
    help = help_text(
        """
        A single Terraform module corresponding to a directory.

        There must only be one `terraform_module` in a directory.

        Use `terraform_modules` to generate `terraform_module` targets for less boilerplate.
        """
    )


class TerraformBackendConfigField(OptionalSingleSourceField):
    alias = "backend_config"
    help = "Configuration to be merged with what is in the configuration file's 'backend' block"


class TerraformVarFilesField(MultipleSourcesField):
    alias = "var_files"
    expected_file_extensions = (".tfvars",)
    help = generate_multiple_sources_field_help_message(
        "Example: `var_files=['common.tfvars', 'prod.tfvars']`"
    )


class TerraformExtraArgs(StringSequenceField):
    alias = "extra_args"
    help = help_text(
        """
        Extra arguments for `terraform apply`
        Example: `extra_args=["-var" "'var0=hihello'"]`"
        """
    )


class TerraformDeploymentTarget(Target):
    alias = "terraform_deployment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TerraformDependenciesField,
        TerraformModuleSourcesField,
        TerraformBackendConfigField,
        TerraformVarFilesField,
        TerraformExtraArgs,
    )
    help = "A deployment of Terraform"


@dataclass(frozen=True)
class TerraformDeploymentFieldSet(FieldSet):
    required_fields = (
        TerraformDependenciesField,
        TerraformModuleSourcesField,
    )
    description: DescriptionField
    sources: TerraformModuleSourcesField
    dependencies: TerraformDependenciesField

    backend_config: TerraformBackendConfigField
    var_files: TerraformVarFilesField
    extra_args: TerraformExtraArgs


class AllTerraformDeploymentTargets(Targets):
    pass


@rule
def all_terraform_deployment_targets(targets: AllTargets) -> AllTerraformDeploymentTargets:
    return AllTerraformDeploymentTargets(
        tgt for tgt in targets if TerraformDeploymentFieldSet.is_applicable(tgt)
    )


def rules():
    return collect_rules()
