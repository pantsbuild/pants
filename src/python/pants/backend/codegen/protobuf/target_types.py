# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import ClassVar, TypeVar

from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.engine.collection import Collection
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    Sources,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    UnexpandedTargets,
    generate_file_level_target,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.docutil import doc_url


# NB: We subclass Dependencies so that specific backends can add dependency injection rules to
# Protobuf targets.
class ProtobufDependencies(Dependencies):
    pass


class ProtobufSources(Sources):
    default = ("*.proto",)
    expected_file_extensions = (".proto",)


class ProtobufGrpcToggle(BoolField):
    alias = "grpc"
    default = False
    help = "Whether to generate gRPC code or not."


class ProtobufLibrary(Target):
    alias = "protobuf_library"
    core_fields = (*COMMON_TARGET_FIELDS, ProtobufDependencies, ProtobufSources, ProtobufGrpcToggle)
    help = f"Protobuf files used to generate various languages.\n\nSee f{doc_url('protobuf')}."


logger = logging.getLogger(__name__)


_T = TypeVar("_T", bound=Target)


@union
@dataclass(frozen=True)
class GenerateTargetsRequest:
    target_class: ClassVar[type[_T]]
    target: _T


class GeneratedTargets(Collection[Target]):
    pass


class GenerateProtobufLibraryFromProtobufLibrary(GenerateTargetsRequest):
    target_class = ProtobufLibrary


@rule
async def generate_protobuf_library_from_protobuf_library(
    request: GenerateProtobufLibraryFromProtobufLibrary, union_membership: UnionMembership
) -> GeneratedTargets:
    paths = await Get(SourcesPaths, SourcesPathsRequest(request.target[ProtobufSources]))
    return GeneratedTargets(
        generate_file_level_target(ProtobufLibrary, request.target, union_membership, file_path=fp)
        for fp in paths.files
    )


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
        UnionRule(GenerateTargetsRequest, GenerateProtobufLibraryFromProtobufLibrary),
    )
