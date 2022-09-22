# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os
from typing import Any, Iterable, Iterator, MutableMapping

import toml
from packaging.utils import NormalizedName
from packaging.utils import canonicalize_name as canonicalize_project_name

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


def parse_pyproject_toml(
    pyproject_toml: str,
    *,
    rel_path: str,
    overrides: MutableMapping[NormalizedName, dict[str, Any]],
) -> Iterator[PipRequirement]:
    parsed = toml.loads(pyproject_toml)
    deps_vals: list[str] = parsed.get("project", {}).get("dependencies", [])
    optional_dependencies = parsed.get("project", {}).get("optional-dependencies", {})
    if not deps_vals and not optional_dependencies:
        raise KeyError(
            softwrap(
                "No section `project.dependencies` or `project.optional-dependencies` "
                f"found in {rel_path}"
            )
        )
    for dep in deps_vals:
        dep, _, _ = dep.partition("--")
        dep = dep.strip().rstrip("\\")
        if not dep or dep.startswith(("#", "-")):
            continue
        yield PipRequirement.parse(dep, description_of_origin=rel_path)
    for tag, opt_dep in optional_dependencies.items():
        for dep in opt_dep:
            req = PipRequirement.parse(dep, description_of_origin=rel_path)
            canonical_project_name = canonicalize_project_name(req.project_name)
            override = overrides.get(canonical_project_name, {})
            tags: list[str] = override.get("tags", [])
            tags.append(tag)
            override["tags"] = tags
            overrides[canonical_project_name] = override
            yield req


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


@rule(
    desc=(
        "Generate `python_requirement` targets from requirements.txt or PEP 621 compliant "
        "pyproject.toml"
    ),
    level=LogLevel.DEBUG,
)
async def generate_from_python_requirement(
    request: GenerateFromPythonRequirementsRequest,
    union_membership: UnionMembership,
    python_setup: PythonSetup,
) -> GeneratedTargets:
    generator = request.generator
    requirements_rel_path = generator[PythonRequirementsSourceField].value
    if os.path.basename(requirements_rel_path) == "pyproject.toml":
        callback = parse_pyproject_callback
    else:
        callback = parse_requirements_callback
    result = await _generate_requirements(
        request,
        union_membership,
        python_setup,
        parse_requirements_callback=callback,
    )
    return GeneratedTargets(request.generator, result)


def parse_requirements_callback(file_contents: bytes, file_path: str) -> Iterator[PipRequirement]:
    return parse_requirements_file(file_contents.decode(), rel_path=file_path)

def parse_pyproject_callback(file_contents: bytes, file_path: str, overrides) -> Iterator[PipRequirement]:
    return parse_pyproject_toml(file_contents.decode(), rel_path=file_path, overrides=overrides)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPythonRequirementsRequest),
    )
