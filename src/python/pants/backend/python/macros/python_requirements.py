# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from typing import Iterable

from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.macros.common_fields import (
    ModuleMappingField,
    RequirementsOverrideField,
    TypeStubsModuleMappingField,
)
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementResolveField,
    PythonRequirementsField,
    PythonRequirementTarget,
    PythonRequirementTypeStubModulesField,
    parse_requirements_file,
)
from pants.core.target_types import (
    TargetGeneratorSourcesHelperSourcesField,
    TargetGeneratorSourcesHelperTarget,
)
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents, GlobMatchErrorBehavior, PathGlobs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    GeneratedTargets,
    GenerateTargetsRequest,
    InvalidFieldException,
    SingleSourceField,
    TargetGenerator,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap


class PythonRequirementsSourceField(SingleSourceField):
    default = "requirements.txt"
    required = False


class PythonRequirementsTargetGenerator(TargetGenerator):
    alias = "python_requirements"
    help = softwrap(
        """
        Generate a `python_requirement` for each entry in a requirements.txt-style file from the
        `source` field.

        This works with pip-style requirements files:
        https://pip.pypa.io/en/latest/reference/requirements-file-format/. However, pip options
        like `--hash` are (for now) ignored.

        Pants will not follow `-r reqs.txt` lines. Instead, add a dedicated `python_requirements`
        target generator for that additional requirements file.
        """
    )
    generated_target_cls = PythonRequirementTarget
    # Note that this does not have a `dependencies` field.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ModuleMappingField,
        TypeStubsModuleMappingField,
        PythonRequirementsSourceField,
        RequirementsOverrideField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (PythonRequirementResolveField,)


class GenerateFromPythonRequirementsRequest(GenerateTargetsRequest):
    generate_from = PythonRequirementsTargetGenerator


@rule(desc="Generate `python_requirement` targets from requirements.txt", level=LogLevel.DEBUG)
async def generate_from_python_requirement(
    request: GenerateFromPythonRequirementsRequest, python_setup: PythonSetup
) -> GeneratedTargets:
    generator = request.generator
    requirements_rel_path = generator[PythonRequirementsSourceField].value
    requirements_full_path = generator[PythonRequirementsSourceField].file_path
    overrides = {
        canonicalize_project_name(k): v
        for k, v in request.require_unparametrized_overrides().items()
    }

    file_tgt = TargetGeneratorSourcesHelperTarget(
        {TargetGeneratorSourcesHelperSourcesField.alias: [requirements_rel_path]},
        Address(
            request.template_address.spec_path,
            target_name=request.template_address.target_name,
            relative_file_path=requirements_rel_path,
        ),
    )

    digest_contents = await Get(
        DigestContents,
        PathGlobs(
            [requirements_full_path],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"{generator}'s field `{PythonRequirementsSourceField.alias}`",
        ),
    )
    requirements = parse_requirements_file(
        digest_contents[0].content.decode(), rel_path=requirements_full_path
    )
    grouped_requirements = itertools.groupby(
        requirements, lambda parsed_req: parsed_req.project_name
    )

    module_mapping = generator[ModuleMappingField].value
    stubs_mapping = generator[TypeStubsModuleMappingField].value

    def generate_tgt(
        project_name: str, parsed_reqs: Iterable[PipRequirement]
    ) -> PythonRequirementTarget:
        normalized_proj_name = canonicalize_project_name(project_name)
        tgt_overrides = overrides.pop(normalized_proj_name, {})
        if Dependencies.alias in tgt_overrides:
            tgt_overrides[Dependencies.alias] = list(tgt_overrides[Dependencies.alias]) + [
                file_tgt.address.spec
            ]

        return PythonRequirementTarget(
            {
                **request.template,
                PythonRequirementsField.alias: list(parsed_reqs),
                PythonRequirementModulesField.alias: module_mapping.get(normalized_proj_name),
                PythonRequirementTypeStubModulesField.alias: stubs_mapping.get(
                    normalized_proj_name
                ),
                # This may get overridden by `tgt_overrides`, which will have already added in
                # the file tgt.
                Dependencies.alias: [file_tgt.address.spec],
                **tgt_overrides,
            },
            request.template_address.create_generated(project_name),
        )

    result = tuple(
        generate_tgt(project_name, parsed_reqs_)
        for project_name, parsed_reqs_ in grouped_requirements
    ) + (file_tgt,)

    if overrides:
        raise InvalidFieldException(
            f"Unused key in the `overrides` field for {request.template_address}: "
            f"{sorted(overrides)}"
        )

    return GeneratedTargets(generator, result)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPythonRequirementsRequest),
    )
