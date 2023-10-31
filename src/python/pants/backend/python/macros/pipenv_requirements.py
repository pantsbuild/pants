# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json

from pants.backend.python.macros.common_fields import (
    ModuleMappingField,
    RequirementsOverrideField,
    TypeStubsModuleMappingField,
)
from pants.backend.python.macros.common_requirements_rule import _generate_requirements
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonRequirementResolveField, PythonRequirementTarget
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    GeneratedTargets,
    GenerateTargetsRequest,
    SingleSourceField,
    TargetGenerator,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.logging import LogLevel
from pants.util.pip_requirement import PipRequirement


class PipenvSourceField(SingleSourceField):
    default = "Pipfile.lock"
    required = False


class PipenvRequirementsTargetGenerator(TargetGenerator):
    alias = "pipenv_requirements"
    help = "Generate a `python_requirement` for each entry in `Pipenv.lock`."
    generated_target_cls = PythonRequirementTarget
    # Note that this does not have a `dependencies` field.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ModuleMappingField,
        TypeStubsModuleMappingField,
        PipenvSourceField,
        RequirementsOverrideField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (PythonRequirementResolveField,)


class GenerateFromPipenvRequirementsRequest(GenerateTargetsRequest):
    generate_from = PipenvRequirementsTargetGenerator


# TODO(#10655): add support for PEP 440 direct references (aka VCS style).
# TODO(#10655): differentiate between Pipfile vs. Pipfile.lock.
@rule(desc="Generate `python_requirement` targets from Pipfile.lock", level=LogLevel.DEBUG)
async def generate_from_pipenv_requirements(
    request: GenerateFromPipenvRequirementsRequest,
    union_membership: UnionMembership,
    python_setup: PythonSetup,
) -> GeneratedTargets:
    result = await _generate_requirements(
        request,
        union_membership,
        python_setup,
        parse_requirements_callback=parse_pipenv_requirements,
    )
    return GeneratedTargets(request.generator, result)


def parse_pipenv_requirements(
    file_contents: bytes, file_path: str = ""
) -> tuple[PipRequirement, ...]:
    lock_info = json.loads(file_contents)

    def _parse_pipenv_requirement(raw_req: str, info: dict) -> PipRequirement:
        if info.get("extras"):
            raw_req += f"[{','.join(info['extras'])}]"
        raw_req += info.get("version", "")
        if info.get("markers"):
            raw_req += f";{info['markers']}"

        return PipRequirement.parse(raw_req)

    return tuple(
        _parse_pipenv_requirement(req, info)
        for req, info in {**lock_info.get("default", {}), **lock_info.get("develop", {})}.items()
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPipenvRequirementsRequest),
    )
