# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from itertools import chain
from typing import Any, Callable, Iterator

import toml

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
from pants.util.requirements import parse_requirements_file
from pants.util.strutil import help_text, softwrap


def parse_pyproject_toml(pyproject_toml: str, *, rel_path: str) -> Iterator[PipRequirement]:
    parsed: dict[str, Any] = toml.loads(pyproject_toml)
    deps_vals: list[str] = parsed.get("project", {}).get("dependencies", [])
    optional_dependencies: dict[str, list[str]] = parsed.get("project", {}).get(
        "optional-dependencies", {}
    )
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
    for dep in chain.from_iterable(optional_dependencies.values()):
        dep, _, _ = dep.partition("--")
        dep = dep.strip().rstrip("\\")
        if not dep or dep.startswith(("#", "-")):
            continue
        req = PipRequirement.parse(dep, description_of_origin=rel_path)
        yield req


class PythonRequirementsSourceField(SingleSourceField):
    default = "requirements.txt"
    required = False


class PythonRequirementsTargetGenerator(TargetGenerator):
    alias = "python_requirements"
    help = help_text(
        """
        Generate a `python_requirement` for each entry in a requirements.txt-style or PEP 621
        compliant `pyproject.toml` file. The choice of parser for the `source` field is determined
        by the file name. If the `source` field ends with `pyproject.toml`, then the file is
        assumed to be a PEP 621 compliant file. Any other file name uses the requirements.txt-style
        parser.

        Further details about pip-style requirements files are available from the PyPA documentation:
        https://pip.pypa.io/en/latest/reference/requirements-file-format/. However, pip options like
        `--hash` are (for now) ignored.

        Pants will not follow `-r reqs.txt` lines. Instead, add a dedicated `python_requirements`
        target generator for that additional requirements file.

        Further details about PEP 621 and `pyproject.toml` files are available from the PEP itself:
        https://peps.python.org/pep-0621/. If the `project.optional-dependencies` table is
        included, Pants will save the key/name of the optional dependency group as a tag on the
        generated `python_requirement`.
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
    callback: Callable[[bytes, str], Iterator[PipRequirement]]
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


def parse_pyproject_callback(file_contents: bytes, file_path: str) -> Iterator[PipRequirement]:
    return parse_pyproject_toml(file_contents.decode(), rel_path=file_path)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPythonRequirementsRequest),
    )
