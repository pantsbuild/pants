# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pathlib import PurePath

from pants.backend.codegen.thrift.apache.python import additional_fields, subsystem
from pants.backend.codegen.thrift.apache.python.additional_fields import PythonSourceRootField
from pants.backend.codegen.thrift.apache.python.subsystem import ThriftPythonSubsystem
from pants.backend.codegen.thrift.apache.rules import (
    GeneratedThriftSources,
    GenerateThriftSourcesRequest,
)
from pants.backend.codegen.thrift.target_types import ThriftDependenciesField, ThriftSourceField
from pants.backend.python.target_types import PythonSourceField
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


class GeneratePythonFromThriftRequest(GenerateSourcesRequest):
    input = ThriftSourceField
    output = PythonSourceField


@rule(desc="Generate Python from Thrift", level=LogLevel.DEBUG)
async def generate_python_from_thrift(
    request: GeneratePythonFromThriftRequest,
    thrift_python: ThriftPythonSubsystem,
) -> GeneratedSources:
    result = await Get(
        GeneratedThriftSources,
        GenerateThriftSourcesRequest(
            thrift_source_field=request.protocol_target[ThriftSourceField],
            lang_id="py",
            lang_options=thrift_python.gen_options,
            lang_name="Python",
        ),
    )

    # We must do some path manipulation on the output digest for it to look like normal sources,
    # including adding back a source root.
    py_source_root = request.protocol_target.get(PythonSourceRootField).value
    if py_source_root:
        # Verify that the python source root specified by the target is in fact a source root.
        source_root_request = SourceRootRequest(PurePath(py_source_root))
    else:
        # The target didn't specify a python source root, so use the thrift_source's source root.
        source_root_request = SourceRootRequest.for_target(request.protocol_target)

    source_root = await Get(SourceRoot, SourceRootRequest, source_root_request)

    source_root_restored = (
        await Get(Snapshot, AddPrefix(result.snapshot.digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, result.snapshot.digest)
    )
    return GeneratedSources(source_root_restored)


class InjectApacheThriftPythonDependencies(InjectDependenciesRequest):
    inject_for = ThriftDependenciesField


@rule
async def inject_apache_thrift_java_dependencies(
    _: InjectApacheThriftPythonDependencies, thrift_python: ThriftPythonSubsystem
) -> InjectedDependencies:
    addresses = await Get(Addresses, UnparsedAddressInputs, thrift_python.runtime_dependencies)
    return InjectedDependencies(addresses)


def rules():
    return (
        *collect_rules(),
        *additional_fields.rules(),
        *subsystem.rules(),
        UnionRule(GenerateSourcesRequest, GeneratePythonFromThriftRequest),
        UnionRule(InjectDependenciesRequest, InjectApacheThriftPythonDependencies),
    )
