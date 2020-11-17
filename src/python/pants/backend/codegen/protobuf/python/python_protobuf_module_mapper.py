# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, Set

from pants.backend.codegen.protobuf.python.python_protobuf_subsystem import PythonProtobufSubsystem
from pants.backend.codegen.protobuf.target_types import ProtobufGrcpToggle, ProtobufSources
from pants.backend.python.dependency_inference.module_mapper import (
    PythonFirstPartyModuleMappingPlugin,
    PythonFirstPartyModuleMappingPluginRequest,
)
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.util_rules.stripped_source_files import StrippedSourceFileNames
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import SourcesPathsRequest, Target, Targets
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


def proto_path_to_py_module(stripped_path: str, *, suffix: str) -> str:
    return stripped_path.replace(".proto", suffix).replace("/", ".")


# This is only used to register our implementation with the plugin hook via unions.
class PythonProtobufMappingRequest(PythonFirstPartyModuleMappingPluginRequest):
    pass


@rule(desc="Creating map of Protobuf targets to generated Python modules", level=LogLevel.DEBUG)
async def map_protobuf_to_python_modules(
    _: PythonProtobufMappingRequest, python_protobuf_subsystem: PythonProtobufSubsystem
) -> PythonFirstPartyModuleMappingPlugin:
    if not python_protobuf_subsystem.dependency_inference:
        return PythonFirstPartyModuleMappingPlugin(FrozenDict())

    all_expanded_targets = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    protobuf_targets = tuple(tgt for tgt in all_expanded_targets if tgt.has_field(ProtobufSources))
    stripped_sources_per_target = await MultiGet(
        Get(StrippedSourceFileNames, SourcesPathsRequest(tgt[ProtobufSources]))
        for tgt in protobuf_targets
    )

    modules_to_addresses: Dict[str, Address] = {}
    modules_with_multiple_owners: Set[str] = set()

    def add_module(module: str, tgt: Target) -> None:
        if module in modules_to_addresses:
            modules_with_multiple_owners.add(module)
        else:
            modules_to_addresses[module] = tgt.address

    for tgt, stripped_sources in zip(protobuf_targets, stripped_sources_per_target):
        for stripped_f in stripped_sources:
            # NB: We don't consider the MyPy plugin, which generates `_pb2.pyi`. The stubs end up
            # sharing the same module as the implementation `_pb2.py`. Because both generated files
            # come from the same original Protobuf target, we're covered.
            add_module(proto_path_to_py_module(stripped_f, suffix="_pb2"), tgt)
            if tgt.get(ProtobufGrcpToggle).value:
                add_module(proto_path_to_py_module(stripped_f, suffix="_pb2_grpc"), tgt)

    # Remove modules with ambiguous owners.
    for ambiguous_module in modules_with_multiple_owners:
        modules_to_addresses.pop(ambiguous_module)

    return PythonFirstPartyModuleMappingPlugin(FrozenDict(modules_to_addresses))


def rules():
    return (
        *collect_rules(),
        UnionRule(PythonFirstPartyModuleMappingPluginRequest, PythonProtobufMappingRequest),
    )
