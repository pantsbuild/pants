# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path

from pants.backend.terraform.target_types import (
    TerraformModulesGeneratingSourcesField,
    TerraformModulesGeneratorTarget,
    TerraformModuleTarget,
)
from pants.core.goals.tailor import group_by_dir
from pants.engine.rules import Get, collect_rules, rule
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
    generate_from = TerraformModulesGeneratorTarget


@rule
async def generate_terraform_module_targets(
    request: GenerateTerraformModuleTargetsRequest,
) -> GeneratedTargets:
    generator = request.generator
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(generator.get(TerraformModulesGeneratingSourcesField))
    )

    dir_to_filenames = group_by_dir(sources_paths.files)
    dirs_with_terraform_files = []
    for dir, filenames in dir_to_filenames.items():
        if any(filename.endswith(".tf") for filename in filenames):
            dirs_with_terraform_files.append(dir)

    def gen_target(dir: str) -> Target:
        generated_target_fields = {}
        for field in generator.field_values.values():
            value: ImmutableValue | None
            if isinstance(field, Sources):
                value = tuple(sorted(os.path.join(dir, f) for f in dir_to_filenames[dir]))
            else:
                value = field.value
            generated_target_fields[field.alias] = value
        return TerraformModuleTarget(
            generated_target_fields, generator.address.create_generated(dir)
        )

    return GeneratedTargets(
        request.generator, [gen_target(dir) for dir in dirs_with_terraform_files]
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTerraformModuleTargetsRequest),
    ]
