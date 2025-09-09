# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.codegen.thrift import jvm_symbol_mapper
from pants.backend.codegen.thrift.jvm_symbol_mapper import (
    FirstPartyThriftJvmMappingRequest,
    map_first_party_thrift_targets_to_jvm_symbols,
)
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest, SymbolMap


class FirstPartyThriftScroogeScalaTargetsMappingRequest(FirstPartyMappingRequest):
    pass


@rule
async def map_first_party_thrift_scrooge_java_targets_to_symbols(
    _: FirstPartyThriftScroogeScalaTargetsMappingRequest,
) -> SymbolMap:
    return await map_first_party_thrift_targets_to_jvm_symbols(
        FirstPartyThriftJvmMappingRequest(
            extra_lang_ids=("scala",), extra_namespace_directives=("#@namespace",)
        ),
        **implicitly(),
    )


def rules():
    return [
        *collect_rules(),
        *jvm_symbol_mapper.rules(),
        UnionRule(FirstPartyMappingRequest, FirstPartyThriftScroogeScalaTargetsMappingRequest),
    ]
