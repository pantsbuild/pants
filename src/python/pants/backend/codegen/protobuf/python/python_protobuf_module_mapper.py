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
    ResolveName,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField
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
    python_setup: PythonSetup,
    _: PythonProtobufMappingMarker,
) -> FirstPartyPythonMappingImpl:

    stripped_file_per_target = await MultiGet(
        Get(StrippedFileName, StrippedFileNameRequest(tgt[ProtobufSourceField].file_path))
        for tgt in protobuf_targets
    )

    resolves_to_modules_to_providers: DefaultDict[
        ResolveName, DefaultDict[str, list[ModuleProvider]]
    ] = defaultdict(lambda: defaultdict(list))
    for tgt, stripped_file in zip(protobuf_targets, stripped_file_per_target):
        resolve = tgt[PythonResolveField].normalized_value(python_setup)

        # NB: We don't consider the MyPy plugin, which generates `_pb2.pyi`. The stubs end up
        # sharing the same module as the implementation `_pb2.py`. Because both generated files
        # come from the same original Protobuf target, we're covered.
        module = proto_path_to_py_module(stripped_file.value, suffix="_pb2")
        resolves_to_modules_to_providers[resolve][module].append(
            ModuleProvider(tgt.address, ModuleProviderType.IMPL)
        )
        if tgt.get(ProtobufGrpcToggleField).value:
            module = proto_path_to_py_module(stripped_file.value, suffix="_pb2_grpc")
            resolves_to_modules_to_providers[resolve][module].append(
                ModuleProvider(tgt.address, ModuleProviderType.IMPL)
            )

    return FirstPartyPythonMappingImpl.create(resolves_to_modules_to_providers)


def rules():
    return (
        *collect_rules(),
        UnionRule(FirstPartyPythonMappingImplMarker, PythonProtobufMappingMarker),
    )
