# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from typing import Optional

from pants.backend.terraform.target_types import (
    TerraformModule,
    TerraformModules,
    TerraformModulesSources,
)
from pants.build_graph.address import Address
from pants.core.goals.tailor import group_by_dir
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    GeneratedTargets,
    GenerateTargetsRequest,
    HydratedSources,
    HydrateSourcesRequest,
    ImmutableValue,
    Sources,
    Target,
)
from pants.engine.unions import UnionRule


class GenerateTerraformModuleTargetsRequest(GenerateTargetsRequest):
    generate_from = TerraformModules


@rule
async def generate_terraform_module_targets(
    request: GenerateTerraformModuleTargetsRequest,
) -> GeneratedTargets:
    # Hydrate the sources referenced by the generator.
    sources = await Get(
        HydratedSources, HydrateSourcesRequest(request.generator.get(TerraformModulesSources))
    )

    # Group the sources by directory and find which directories have Terraform files present.
    dir_to_filenames = group_by_dir(sources.snapshot.files)
    dirs_with_terraform_files = []
    for dir, filenames in dir_to_filenames.items():
        if any(filename.endswith(".tf") for filename in filenames):
            dirs_with_terraform_files.append(dir)

    def gen_target(dir: str) -> Target:
        generated_target_fields = {}
        for field in request.generator.field_values.values():
            value: Optional[ImmutableValue]
            if isinstance(field, Sources):
                value = tuple(dir_to_filenames[dir])
            else:
                value = field.value
            generated_target_fields[field.alias] = value
        return TerraformModule(
            generated_target_fields,
            Address(
                dir,
                target_name="tf_mod",
            ),
        )

    return GeneratedTargets(gen_target(dir) for dir in dirs_with_terraform_files)


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTerraformModuleTargetsRequest),
    ]
