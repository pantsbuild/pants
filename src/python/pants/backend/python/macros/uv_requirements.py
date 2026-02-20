# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from collections.abc import Iterator
from functools import partial
from pathlib import PurePath

from pants.backend.python.macros.common_fields import (
    ModuleMappingField,
    RequirementsOverrideField,
    TypeStubsModuleMappingField,
)
from pants.backend.python.macros.common_requirements_rule import _generate_requirements
from pants.backend.python.macros.poetry_requirements import PyProjectToml
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonRequirementResolveField, PythonRequirementTarget
from pants.base.build_root import BuildRoot
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
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


def parse_pyproject_toml(pyproject_toml: PyProjectToml) -> Iterator[PipRequirement]:
    parsed = pyproject_toml.parse()
    if uv_vals := parsed.get("dependency-groups") is not None:
        legacy = False
    elif uv_vals := parsed.get("tool", {}).get("uv") is not None:
        legacy = True
    else:
        raise KeyError(
            softwrap(
                f"""
                No section `dependency-groups` or 'tool.uv' found in {pyproject_toml.toml_relpath},
                which is loaded by Pants from a `uv_requirements` macro.

                Did you mean to set up uv?
                """
            )
        )

    # See https://docs.astral.sh/uv/concepts/dependencies/#development-dependencies
    # and https://docs.astral.sh/uv/concepts/projects/dependencies/#legacy-dev-dependencies
    # This should be a list of PEP 508 compliant strings.
    dev_dependencies = uv_vals.get("dev-dependencies", []) if legacy else uv_vals.get("dev", [])
    if not dev_dependencies:
        logger.warning(
            softwrap(
                f"""
                No requirements defined in `dependency-groups.dev` or 'dev-dependencies' in
                {pyproject_toml.toml_relpath}, which is loaded by Pants from a uv_requirements
                macro. Did you mean to populate this section with requirements?.
                """
            )
        )

    for dep in dev_dependencies:
        dep = dep.strip()
        if not dep or dep.startswith("#"):
            continue
        yield PipRequirement.parse(dep, description_of_origin=str(pyproject_toml.toml_relpath))


def parse_uv_requirements(
    build_root: BuildRoot, file_contents: bytes, file_path: str
) -> set[PipRequirement]:
    return set(
        parse_pyproject_toml(
            PyProjectToml(
                build_root=PurePath(build_root.path),
                toml_relpath=PurePath(file_path),
                toml_contents=file_contents.decode(),
            )
        )
    )


# ---------------------------------------------------------------------------------
# Target generator
# ---------------------------------------------------------------------------------


class UvRequirementsSourceField(SingleSourceField):
    default = "pyproject.toml"
    required = False


class UvRequirementsTargetGenerator(TargetGenerator):
    alias = "uv_requirements"
    help = (
        "Generate a `python_requirement` for each entry in `pyproject.toml` under the "
        "`[dependency-groups]` or `[tool.uv]` (legacy) section."
    )
    generated_target_cls = PythonRequirementTarget
    # Note that this does not have a `dependencies` field.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ModuleMappingField,
        TypeStubsModuleMappingField,
        UvRequirementsSourceField,
        RequirementsOverrideField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (PythonRequirementResolveField,)


class GenerateFromUvRequirementsRequest(GenerateTargetsRequest):
    generate_from = UvRequirementsTargetGenerator


@rule(desc="Generate `python_requirement` targets from uv pyproject.toml", level=LogLevel.DEBUG)
async def generate_from_uv_requirement(
    request: GenerateFromUvRequirementsRequest,
    build_root: BuildRoot,
    union_membership: UnionMembership,
    python_setup: PythonSetup,
) -> GeneratedTargets:
    result = await _generate_requirements(
        request,
        union_membership,
        python_setup,
        parse_requirements_callback=partial(parse_uv_requirements, build_root),
    )
    return GeneratedTargets(request.generator, result)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromUvRequirementsRequest),
    )
