# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterator

from pants.backend.python.macros.common_fields import (
    ModuleMappingField,
    RequirementsOverrideField,
    TypeStubsModuleMappingField,
)
from pants.backend.python.macros.common_requirements_rule import _generate_requirements
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PythonRequirementResolveField,
    PythonRequirementTarget,
    parse_requirements_file,
)
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
    request: GenerateFromPythonRequirementsRequest,
    union_membership: UnionMembership,
    python_setup: PythonSetup,
) -> GeneratedTargets:
    result = await _generate_requirements(
        request,
        union_membership,
        python_setup,
        parse_requirements_callback=parse_requirements_callback,
    )
    return GeneratedTargets(request.generator, result)


def parse_requirements_callback(file_contents: bytes, file_path: str) -> Iterator[PipRequirement]:
    return parse_requirements_file(file_contents.decode(), rel_path=file_path)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPythonRequirementsRequest),
    )
