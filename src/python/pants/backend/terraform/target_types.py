# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.internals.native_engine import AddressInput
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AllTargets,
    AsyncFieldMixin,
    Dependencies,
    DescriptionField,
    FieldSet,
    MultipleSourcesField,
    OptionalSingleSourceField,
    StringField,
    Target,
    Targets,
    generate_multiple_sources_field_help_message,
)
from pants.util.strutil import help_text, softwrap


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


class TerraformRootModuleField(StringField, AsyncFieldMixin):
    """The module to use as the root module for a Terraform deployment."""

    required = True
    alias = "root_module"
    help = help_text(
        """
        The Terraform module to use as the root module.

        Example: `root_module=":my_module"`
        """
    )

    def to_address_input(self) -> AddressInput:
        if not self.value:
            raise ValueError(
                softwrap(
                    f"""
            A Terraform deployment must have a nonempty {self.alias} field,
             but {self.address} was empty"""
                )
            )
        return AddressInput.parse(
            self.value,
            relative_to=self.address.spec_path,
            description_of_origin=f"the `{self.alias} field in the `{TerraformDeploymentTarget.alias}` target {self.address}",
        )


class TerraformBackendConfigField(OptionalSingleSourceField):
    alias = "backend_config"
    help = "Configuration to be merged with what is in the configuration file's 'backend' block"


class TerraformVarFileSourcesField(MultipleSourcesField):
    alias = "var_files"
    expected_file_extensions = (".tfvars",)
    help = generate_multiple_sources_field_help_message(
        "Example: `var_files=['common.tfvars', 'prod.tfvars']`"
    )


class TerraformDeploymentTarget(Target):
    alias = "terraform_deployment"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TerraformDependenciesField,
        TerraformRootModuleField,
        TerraformBackendConfigField,
        TerraformVarFileSourcesField,
    )
    help = "A deployment of Terraform"


@dataclass(frozen=True)
class TerraformDeploymentFieldSet(FieldSet):
    required_fields = (
        TerraformDependenciesField,
        TerraformRootModuleField,
    )
    description: DescriptionField
    root_module: TerraformRootModuleField
    dependencies: TerraformDependenciesField

    backend_config: TerraformBackendConfigField
    var_files: TerraformVarFileSourcesField


class AllTerraformDeploymentTargets(Targets):
    pass


@rule
def all_terraform_deployment_targets(targets: AllTargets) -> AllTerraformDeploymentTargets:
    return AllTerraformDeploymentTargets(
        tgt for tgt in targets if TerraformDeploymentFieldSet.is_applicable(tgt)
    )


def rules():
    return collect_rules()
