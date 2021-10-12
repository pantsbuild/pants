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
    MultipleSourcesField,
    SourcesPaths,
    SourcesPathsRequest,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.dirutil import fast_relpath


class GenerateTerraformModuleTargetsRequest(GenerateTargetsRequest):
    generate_from = TerraformModulesGeneratorTarget


@rule
async def generate_terraform_module_targets(
    request: GenerateTerraformModuleTargetsRequest, union_membership: UnionMembership
) -> GeneratedTargets:
    generator = request.generator
    sources_paths = await Get(
        SourcesPaths, SourcesPathsRequest(generator.get(TerraformModulesGeneratingSourcesField))
    )

    dir_to_filenames = group_by_dir(sources_paths.files)
    matched_dirs = [dir for dir, filenames in dir_to_filenames.items() if filenames]

    def gen_target(dir: str) -> TerraformModuleTarget:
        generated_target_fields = {}
        relpath_to_generator = fast_relpath(dir, generator.address.spec_path)
        for field in generator.field_values.values():
            value: ImmutableValue | None
            if isinstance(field, MultipleSourcesField):
                value = tuple(
                    os.path.join(relpath_to_generator, f) for f in sorted(dir_to_filenames[dir])
                )
            else:
                value = field.value
            generated_target_fields[field.alias] = value
        return TerraformModuleTarget(
            generated_target_fields,
            generator.address.create_generated(relpath_to_generator or "."),
            union_membership,
            residence_dir=dir,
        )

    return GeneratedTargets(request.generator, [gen_target(dir) for dir in matched_dirs])


def rules():
    return [
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTerraformModuleTargetsRequest),
    ]
