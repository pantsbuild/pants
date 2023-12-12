# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from pants.backend.codegen.thrift import jvm_symbol_mapper
from pants.backend.codegen.thrift.jvm_symbol_mapper import FirstPartyJvmMappingRequest
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.jvm.dependency_inference.symbol_mapper import FirstPartyMappingRequest


class FirstPartyThriftScroogeScalaTargetsMappingRequest(FirstPartyMappingRequest):
    pass


@rule
async def map_first_party_thrift_scrooge_scala_targets_to_symbols(
    _: FirstPartyThriftScroogeScalaTargetsMappingRequest,
) -> FirstPartyJvmMappingRequest:
    return FirstPartyJvmMappingRequest(
        lang_ids=("java", "scala"), extra_namespace_directives=("#@namespace",)
    )


def rules():
    return [
        *collect_rules(),
        *jvm_symbol_mapper.rules(),
        UnionRule(FirstPartyMappingRequest, FirstPartyThriftScroogeScalaTargetsMappingRequest),
    ]
