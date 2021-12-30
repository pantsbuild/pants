# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from typing import DefaultDict

from pants.backend.codegen.protobuf.target_types import (
    AllProtobufTargets,
    ProtobufGrpcToggleField,
    ProtobufSourceField,
)
from pants.backend.python.dependency_inference.module_mapper import (
    FirstPartyPythonMappingImpl,
    FirstPartyPythonMappingImplMarker,
    ModuleProvider,
    ModuleProviderType,
)
from pants.core.util_rules.stripped_source_files import StrippedFileName, StrippedFileNameRequest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


def proto_path_to_py_module(stripped_path: str, *, suffix: str) -> str:
    return stripped_path.replace(".proto", suffix).replace("/", ".")


# This is only used to register our implementation with the plugin hook via unions.
class PythonProtobufMappingMarker(FirstPartyPythonMappingImplMarker):
    pass


@rule(desc="Creating map of Protobuf targets to generated Python modules", level=LogLevel.DEBUG)
async def map_protobuf_to_python_modules(
    protobuf_targets: AllProtobufTargets,
    _: PythonProtobufMappingMarker,
) -> FirstPartyPythonMappingImpl:
    stripped_file_per_target = await MultiGet(
        Get(StrippedFileName, StrippedFileNameRequest(tgt[ProtobufSourceField].file_path))
        for tgt in protobuf_targets
    )

    modules_to_providers: DefaultDict[str, list[ModuleProvider]] = defaultdict(list)
    for tgt, stripped_file in zip(protobuf_targets, stripped_file_per_target):
        # NB: We don't consider the MyPy plugin, which generates `_pb2.pyi`. The stubs end up
        # sharing the same module as the implementation `_pb2.py`. Because both generated files
        # come from the same original Protobuf target, we're covered.
        modules_to_providers[proto_path_to_py_module(stripped_file.value, suffix="_pb2")].append(
            ModuleProvider(tgt.address, ModuleProviderType.IMPL)
        )
        if tgt.get(ProtobufGrpcToggleField).value:
            modules_to_providers[
                proto_path_to_py_module(stripped_file.value, suffix="_pb2_grpc")
            ].append(ModuleProvider(tgt.address, ModuleProviderType.IMPL))

    return FirstPartyPythonMappingImpl(
        (k, tuple(sorted(v))) for k, v in sorted(modules_to_providers.items())
    )


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, PythonProtobufMappingMarker),
    )
