# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.codegen.thrift.scrooge.rules import (
    GeneratedScroogeThriftSources,
    GenerateScroogeThriftSourcesRequest,
)
from pants.backend.codegen.thrift.scrooge.scala.subsystem import ScroogeScalaSubsystem
from pants.backend.codegen.thrift.target_types import ThriftDependenciesField, ThriftSourceField
from pants.backend.scala.target_types import ScalaSourceField
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import AddPrefix, Digest, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    InjectDependenciesRequest,
    InjectedDependencies,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


class GenerateScalaFromThriftRequest(GenerateSourcesRequest):
    input = ThriftSourceField
    output = ScalaSourceField


class InjectScroogeScalaDependencies(InjectDependenciesRequest):
    inject_for = ThriftDependenciesField


@rule(desc="Generate Scala from Thrift with Scrooge", level=LogLevel.DEBUG)
async def generate_scala_from_thrift_with_scrooge(
    request: GenerateScalaFromThriftRequest,
) -> GeneratedSources:
    result = await Get(
        GeneratedScroogeThriftSources,
        GenerateScroogeThriftSourcesRequest(
            thrift_source_field=request.protocol_target[ThriftSourceField],
            lang_id="scala",
            lang_name="Scala",
        ),
    )

    source_root = await Get(
        SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(result.snapshot.digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, result.snapshot.digest)
    )
    return GeneratedSources(source_root_restored)


@rule
async def inject_scrooge_scala_dependencies(
    _: InjectScroogeScalaDependencies, scrooge: ScroogeScalaSubsystem
) -> InjectedDependencies:
    addresses = await Get(Addresses, UnparsedAddressInputs, scrooge.runtime_dependencies)
    return InjectedDependencies(addresses)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateSourcesRequest, GenerateScalaFromThriftRequest),
        UnionRule(InjectDependenciesRequest, InjectScroogeScalaDependencies),
    )
