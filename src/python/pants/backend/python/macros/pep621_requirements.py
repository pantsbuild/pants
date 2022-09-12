# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
from typing import Any, Iterable, Iterator, MutableMapping

import toml
from packaging.utils import NormalizedName
from packaging.utils import canonicalize_name as canonicalize_project_name

from pants.backend.python.macros.common_fields import (
    ModuleMappingField,
    RequirementsOverrideField,
    TypeStubsModuleMappingField,
)
from pants.backend.python.pip_requirement import PipRequirement
from pants.backend.python.target_types import (
    PythonRequirementModulesField,
    PythonRequirementResolveField,
    PythonRequirementsField,
    PythonRequirementTarget,
    PythonRequirementTypeStubModulesField,
)
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.build_graph.address import Address
from pants.core.target_types import (
    TargetGeneratorSourcesHelperSourcesField,
    TargetGeneratorSourcesHelperTarget,
)
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    GeneratedTargets,
    GenerateTargetsRequest,
    InvalidFieldException,
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


class PEP621RequirementsSourceField(SingleSourceField):
    default = "pyproject.toml"
    required = False


class PEP621RequirementsTargetGenerator(TargetGenerator):
    alias = "pep621_requirements"
    help = "Generate a `python_requirement` for each entry in a PEP 621 compliant pyproject.toml."
    generated_target_cls = PythonRequirementTarget
    # Note that this does not have a `dependencies` field.
    core_fields = (
        *COMMON_TARGET_FIELDS,
        ModuleMappingField,
        TypeStubsModuleMappingField,
        PEP621RequirementsSourceField,
        RequirementsOverrideField,
    )
    copied_fields = COMMON_TARGET_FIELDS
    moved_fields = (PythonRequirementResolveField,)


class GenerateFromPEP621RequirementsRequest(GenerateTargetsRequest):
    generate_from = PEP621RequirementsTargetGenerator


@rule(
    desc="Generate `python_requirement` targets from PEP621 pyproject.toml",
    level=LogLevel.DEBUG,
)
async def generate_from_pep621_requirement(
    request: GenerateFromPEP621RequirementsRequest, union_membership: UnionMembership
) -> GeneratedTargets:
    generator = request.generator
    pyproject_rel_path = generator[PEP621RequirementsSourceField].value
    pyproject_full_path = generator[PEP621RequirementsSourceField].file_path
    overrides = {
        canonicalize_project_name(k): v
        for k, v in request.require_unparametrized_overrides().items()
    }

    file_tgt = TargetGeneratorSourcesHelperTarget(
        {TargetGeneratorSourcesHelperSourcesField.alias: pyproject_rel_path},
        Address(
            request.template_address.spec_path,
            target_name=request.template_address.target_name,
            relative_file_path=pyproject_rel_path,
        ),
    )

    digest_contents = await Get(
        DigestContents,
        PathGlobs(
            [pyproject_full_path],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"{generator}'s field `{PEP621RequirementsSourceField.alias}`",
        ),
    )
    requirements = parse_pyproject_toml(
        digest_contents[0].content.decode(),
        rel_path=pyproject_full_path,
        overrides=overrides,
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
                # This may get overridden by `tgt_overrides`, which will have already
                # added in the file tgt.
                Dependencies.alias: [file_tgt.address.spec],
                **tgt_overrides,
            },
            request.template_address.create_generated(project_name),
            union_membership,
        )

    result = tuple(
        generate_tgt(project_name, parsed_reqs_)
        for project_name, parsed_reqs_ in grouped_requirements
    ) + (file_tgt,)

    if overrides:
        raise InvalidFieldException(
            softwrap(
                f"""
                Unused key in the `overrides` field for {request.template_address}:
                {sorted(overrides)}
                """
            )
        )

    return GeneratedTargets(generator, result)


def rules() -> tuple[Rule | UnionRule, ...]:
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateFromPEP621RequirementsRequest),
    )
