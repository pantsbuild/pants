# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.codegen.protobuf import jvm_symbol_mapper
from pants.backend.codegen.protobuf.jvm_symbol_mapper import (
    FirstPartyProtobufJvmMappingRequest,
    map_first_party_protobuf_jvm_targets_to_symbols,
)
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference import symbol_mapper
from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest, SymbolMap


class FirstPartyProtobufJavaTargetsMappingRequest(FirstPartyMappingRequest):
    pass


@rule
async def map_first_party_protobuf_scala_targets_to_symbols(
    _: FirstPartyProtobufJavaTargetsMappingRequest,
) -> SymbolMap:
    return await map_first_party_protobuf_jvm_targets_to_symbols(
        FirstPartyProtobufJvmMappingRequest(capitalize_base_name=True), **implicitly()
    )


def rules():
    return [
        *collect_rules(),
        *symbol_mapper.rules(),
        *jvm_symbol_mapper.rules(),
        UnionRule(FirstPartyMappingRequest, FirstPartyProtobufJavaTargetsMappingRequest),
    ]
