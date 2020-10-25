# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.protobuf.protoc import Protoc
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    BoolField,
    Dependencies,
    InjectDependenciesRequest,
    InjectedDependencies,
    Sources,
    Target,
)
from pants.engine.unions import UnionRule


class ProtobufDependencies(Dependencies):
    pass


class ProtobufSources(Sources):
    default = ("*.proto",)
    expected_file_extensions = (".proto",)


class ProtobufGrcpToggle(BoolField):
    """Whether to generate gRPC code or not."""

    alias = "grpc"
    default = False


class ProtobufLibrary(Target):
    """Protobuf files used to generate various languages.

    See https://www.pantsbuild.org/docs/protobuf.
    """

    alias = "protobuf_library"
    core_fields = (*COMMON_TARGET_FIELDS, ProtobufDependencies, ProtobufSources, ProtobufGrcpToggle)


class InjectProtobufDependencies(InjectDependenciesRequest):
    inject_for = ProtobufDependencies


@rule
async def inject_dependencies(
    _: InjectProtobufDependencies, protoc: Protoc
) -> InjectedDependencies:
    addresses = await Get(
        Addresses, UnparsedAddressInputs(protoc.runtime_targets, owning_address=None)
    )
    return InjectedDependencies(addresses)


def rules():
    return [
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectProtobufDependencies),
    ]
