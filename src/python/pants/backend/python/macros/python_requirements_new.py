# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
import os.path
from dataclasses import dataclass
from typing import ClassVar, TypeVar

from pants.backend.python.target_types import (
    ModuleMappingField,
    PythonRequirementLibrary,
    PythonRequirementsField,
    PythonRequirementsMacro,
    PythonRequirementsRelpath,
    TypeStubsModuleMappingField,
    parse_requirements_file,
)
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.fs import DigestContents, GlobMatchErrorBehavior, PathGlobs
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import Target, UnexpandedTargets, WrappedTarget
from pants.engine.unions import UnionMembership, UnionRule, union

logger = logging.getLogger(__name__)


_T = TypeVar("_T", bound=Target)


@union
@dataclass(frozen=True)
class GenerateTargetsRequest:
    target_class: ClassVar[type[_T]]
    target: _T


class GeneratePythonRequirementLibrariesFromPythonRequirements(GenerateTargetsRequest):
    target_class = PythonRequirementsMacro


class GeneratedTargets(Collection[Target]):
    pass


@rule
async def generate_python_requirement_libraries_from_requirements_file(
    request: GeneratePythonRequirementLibrariesFromPythonRequirements,
) -> GeneratedTargets:
    relpath = os.path.join(
        request.target.address.spec_path, request.target[PythonRequirementsRelpath].value
    )
    digest_contents = await Get(
        DigestContents,
        PathGlobs(
            [relpath],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin=f"{request.target}'s field `{PythonRequirementsRelpath.alias}`",
        ),
    )
    requirements = parse_requirements_file(digest_contents[0].content.decode(), rel_path=relpath)
    grouped_requirements = itertools.groupby(
        requirements, lambda parsed_req: parsed_req.project_name
    )
    result = []
    module_mapping = {}
    type_stubs_module_mapping = {}
    for project_name, parsed_reqs in grouped_requirements:
        req_module_mapping = (
            {project_name: module_mapping[project_name]}
            if module_mapping and project_name in module_mapping
            else None
        )
        stubs_module_mapping = (
            {project_name: type_stubs_module_mapping[project_name]}
            if type_stubs_module_mapping and project_name in type_stubs_module_mapping
            else None
        )
        generated_tgt = PythonRequirementLibrary(
            {
                PythonRequirementsField.alias: list(parsed_reqs),
                ModuleMappingField.alias: req_module_mapping,
                TypeStubsModuleMappingField.alias: stubs_module_mapping,
            },
            Address(request.target.address.spec_path, target_name=project_name),
        )
        result.append(generated_tgt)

    return GeneratedTargets(result)


class TargetGenSubsystem(GoalSubsystem):
    name = "target-gen"
    help = "Foo"
    required_union_implementations = (GenerateTargetsRequest,)


class TargetGen(Goal):
    subsystem_cls = TargetGenSubsystem


@goal_rule
async def gen_targets(union_membership: UnionMembership) -> TargetGen:
    target_types_to_generate_requests = {
        request_cls.target_class: request_cls
        for request_cls in union_membership[GenerateTargetsRequest]
    }

    all_build_targets = await Get(UnexpandedTargets, AddressSpecs([DescendantAddresses("")]))
    generate_requests = []
    for tgt in all_build_targets:
        tgt_type = type(tgt)
        if tgt_type not in target_types_to_generate_requests:
            continue
        generate_requests.append(target_types_to_generate_requests[tgt_type](tgt))

    all_generated = await MultiGet(
        Get(GeneratedTargets, GenerateTargetsRequest, request) for request in generate_requests
    )
    logger.error([tgt.address.spec for generated in all_generated for tgt in generated])
    return TargetGen(exit_code=0)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GeneratePythonRequirementLibrariesFromPythonRequirements),
    )
