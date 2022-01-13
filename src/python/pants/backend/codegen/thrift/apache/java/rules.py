# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.thrift.apache.java import subsystem
from pants.backend.codegen.thrift.apache.java.subsystem import ApacheThriftJavaSubsystem
from pants.backend.codegen.thrift.apache.rules import (
    GeneratedThriftSources,
    GenerateThriftSourcesRequest,
)
from pants.backend.codegen.thrift.target_types import ThriftDependenciesField, ThriftSourceField
from pants.backend.java.target_types import JavaSourceField
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


class GenerateJavaFromThriftRequest(GenerateSourcesRequest):
    input = ThriftSourceField
    output = JavaSourceField


@rule(desc="Generate Java from Thrift", level=LogLevel.DEBUG)
async def generate_java_from_thrift(
    request: GenerateJavaFromThriftRequest,
    thrift_java: ApacheThriftJavaSubsystem,
) -> GeneratedSources:
    result = await Get(
        GeneratedThriftSources,
        GenerateThriftSourcesRequest(
            thrift_source_field=request.protocol_target[ThriftSourceField],
            lang_id="java",
            lang_options=thrift_java.gen_options,
            lang_name="Java",
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


class InjectApacheThriftJavaDependencies(InjectDependenciesRequest):
    inject_for = ThriftDependenciesField


@rule
async def inject_apache_thrift_java_dependencies(
    _: InjectApacheThriftJavaDependencies, thrift_java: ApacheThriftJavaSubsystem
) -> InjectedDependencies:
    addresses = await Get(Addresses, UnparsedAddressInputs, thrift_java.runtime_dependencies)
    return InjectedDependencies(addresses)


def rules():
    return (
        *collect_rules(),
        *subsystem.rules(),
        UnionRule(GenerateSourcesRequest, GenerateJavaFromThriftRequest),
        UnionRule(InjectDependenciesRequest, InjectApacheThriftJavaDependencies),
    )
