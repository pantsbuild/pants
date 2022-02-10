# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json

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
    PythonRequirementsFileSourcesField,
    PythonRequirementsFileTarget,
    PythonRequirementTarget,
    PythonRequirementTypeStubModulesField,
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
    StringField,
    Target,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


class PipenvSourceField(SingleSourceField):
    default = "Pipfile.lock"
    required = False


class PipenvPipfileTargetField(StringField):
    alias = "pipfile_target"
    help = "Deprecated: no longer necessary."
    removal_version = "2.11.0.dev0"
    removal_hint = "This field is no longer necessary."


class PipenvRequirementsTargetGenerator(Target):
    alias = "pipenv_requirements"
    help = "Generate a `python_requirement` for each entry in `Pipenv.lock`."
    # Note that this does not have a `dependencies` field.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ModuleMappingField,
        TypeStubsModuleMappingField,
        PipenvSourceField,
        PipenvPipfileTargetField,
        RequirementsOverrideField,
        PythonRequirementResolveField,
    )


class GenerateFromPipenvRequirementsRequest(GenerateTargetsRequest):
    generate_from = PipenvRequirementsTargetGenerator


# TODO(#10655): add support for PEP 440 direct references (aka VCS style).
# TODO(#10655): differentiate between Pipfile vs. Pipfile.lock.
@rule(desc="Generate `python_requirement` targets from Pipfile.lock", level=LogLevel.DEBUG)
async def generate_from_pipenv_requirement(
    request: GenerateFromPipenvRequirementsRequest, python_setup: PythonSetup
) -> GeneratedTargets:
    generator = request.generator
    lock_rel_path = generator[PipenvSourceField].value
    lock_full_path = generator[PipenvSourceField].file_path

    file_tgt = PythonRequirementsFileTarget(
        {PythonRequirementsFileSourcesField.alias: lock_rel_path},
        Address(
            generator.address.spec_path,
            target_name=generator.address.target_name,
            relative_file_path=lock_rel_path,
        ),
    )

    digest_contents = await Get(
        DigestContents,
        PathGlobs(
            [lock_full_path],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"{generator}'s field `{PipenvSourceField.alias}`",
        ),
    )
    lock_info = json.loads(digest_contents[0].content)

    # Validate the resolve is legal.
    generator[PythonRequirementResolveField].normalized_value(python_setup)

    module_mapping = generator[ModuleMappingField].value
    stubs_mapping = generator[TypeStubsModuleMappingField].value
    overrides = generator[RequirementsOverrideField].flatten_and_normalize()
    inherited_fields = {
        field.alias: field.value
        for field in request.generator.field_values.values()
        if isinstance(field, (*COMMON_TARGET_FIELDS, PythonRequirementResolveField))
    }

    def generate_tgt(raw_req: str, info: dict) -> PythonRequirementTarget:
        if info.get("extras"):
            raw_req += f"[{','.join(info['extras'])}]"
        raw_req += info.get("version", "")
        if info.get("markers"):
            raw_req += f";{info['markers']}"

        parsed_req = PipRequirement.parse(raw_req)
        normalized_proj_name = canonicalize_project_name(parsed_req.project_name)
        tgt_overrides = overrides.pop(normalized_proj_name, {})
        if Dependencies.alias in tgt_overrides:
            tgt_overrides[Dependencies.alias] = list(tgt_overrides[Dependencies.alias]) + [
                file_tgt.address.spec
            ]

        return PythonRequirementTarget(
            {
                **inherited_fields,
                PythonRequirementsField.alias: [parsed_req],
                PythonRequirementModulesField.alias: module_mapping.get(normalized_proj_name),
                PythonRequirementTypeStubModulesField.alias: stubs_mapping.get(
                    normalized_proj_name
                ),
                # This may get overridden by `tgt_overrides`, which will have already added in
                # the file tgt.
                Dependencies.alias: [file_tgt.address.spec],
                **tgt_overrides,
            },
            generator.address.create_generated(parsed_req.project_name),
        )

    result = tuple(
        generate_tgt(req, info)
        for req, info in {**lock_info.get("default", {}), **lock_info.get("develop", {})}.items()
    ) + (file_tgt,)

    if overrides:
        raise InvalidFieldException(
            f"Unused key in the `overrides` field for {request.generator.address}: "
            f"{sorted(overrides)}"
        )

    return GeneratedTargets(generator, result)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPipenvRequirementsRequest),
    )
