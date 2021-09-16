# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

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
    ImmutableValue,
    Sources,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
)
from pants.engine.unions import UnionRule


class GenerateTerraformModuleTargetsRequest(GenerateTargetsRequest):
    generate_from = TerraformModules


@rule
async def generate_terraform_module_targets(
    request: GenerateTerraformModuleTargetsRequest,
) -> GeneratedTargets:
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(request.generator.get(TerraformModulesSources))
    )

    dir_to_filenames = group_by_dir(sources_paths.files)
    dirs_with_terraform_files = []
    for dir, filenames in dir_to_filenames.items():
        if any(filename.endswith(".tf") for filename in filenames):
            dirs_with_terraform_files.append(dir)

    def gen_target(dir: str) -> Target:
        generated_target_fields = {}
        for field in request.generator.field_values.values():
            value: ImmutableValue | None
            if isinstance(field, Sources):
                value = tuple(dir_to_filenames[dir])
            else:
                value = field.value
            generated_target_fields[field.alias] = value
        return TerraformModule(
            generated_target_fields,
            # TODO(12891): Make this be:
            #   Address(
            #       request.generator.address.spec_path,
            #       target_name=request.generator.target_name,
            #       generated_name=dir
            #   )
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
