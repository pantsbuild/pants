# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.codegen.thrift.scrooge import additional_fields
from pants.backend.codegen.thrift.scrooge.additional_fields import ScroogeFinagleBoolField
from pants.backend.codegen.thrift.scrooge.subsystem import ScroogeSubsystem
from pants.backend.codegen.thrift.target_types import ThriftDependenciesField, ThriftSourceField
from pants.backend.java.target_types import JavaSourceField
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    Directory,
    MergeDigests,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    InjectDependenciesRequest,
    InjectedDependencies,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.jvm.jdk_rules import JdkSetup
from pants.jvm.resolve.coursier_fetch import MaterializedClasspath, MaterializedClasspathRequest
from pants.jvm.resolve.jvm_tool import JvmToolLockfileRequest, JvmToolLockfileSentinel
from pants.source.source_root import (
    SourceRoot,
    SourceRootRequest,
    SourceRootsRequest,
    SourceRootsResult,
)
from pants.util.logging import LogLevel


class GenerateScalaFromThriftRequest(GenerateSourcesRequest):
    input = ThriftSourceField
    output = JavaSourceField


class ScroogeToolLockfileSentinel(JvmToolLockfileSentinel):
    resolve_name = ScroogeSubsystem.options_scope


@rule(desc="Generate Scala from Thrift", level=LogLevel.DEBUG)
async def generate_scala_from_thrift_via_scrooge(
    request: GenerateScalaFromThriftRequest,
    scrooge: ScroogeSubsystem,
    jdk_setup: JdkSetup,
    bash: BashBinary,
) -> GeneratedSources:
    output_dir = "_generated_files"
    toolcp_relpath = "__toolcp"

    tool_classpath, transitive_targets, empty_output_dir_digest = await MultiGet(
        Get(
            MaterializedClasspath,
            MaterializedClasspathRequest(
                lockfiles=(scrooge.resolved_lockfile(),),
            ),
        ),
        Get(TransitiveTargets, TransitiveTargetsRequest([request.protocol_target.address])),
        Get(Digest, CreateDigest([Directory(output_dir)])),
    )

    transitive_sources, target_sources = await MultiGet(
        Get(
            SourceFiles,
            SourceFilesRequest(
                tgt[ThriftSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ThriftSourceField)
            ),
        ),
        Get(SourceFiles, SourceFilesRequest([request.protocol_target[ThriftSourceField]])),
    )

    sources_roots = await Get(
        SourceRootsResult,
        SourceRootsRequest,
        SourceRootsRequest.for_files(transitive_sources.snapshot.files),
    )
    deduped_source_root_paths = sorted({sr.path for sr in sources_roots.path_to_root.values()})

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                transitive_sources.snapshot.digest,
                target_sources.snapshot.digest,
                empty_output_dir_digest,
            ]
        ),
    )

    maybe_include_paths = []
    for path in deduped_source_root_paths:
        maybe_include_paths.extend(["-i", path])

    maybe_finagle_option = []
    if request.protocol_target[ScroogeFinagleBoolField].value:
        maybe_finagle_option = ["--finagle"]

    immutable_input_digests = {
        **jdk_setup.immutable_input_digests,
        toolcp_relpath: tool_classpath.digest,
    }

    result = await Get(
        ProcessResult,
        Process(
            argv=[
                *jdk_setup.args(bash, tool_classpath.classpath_entries(toolcp_relpath)),
                "com.twitter.scrooge.Main",
                *maybe_include_paths,
                "--dest",
                output_dir,
                "--language",
                "scala",
                *maybe_finagle_option,
                *target_sources.snapshot.files,
            ],
            input_digest=input_digest,
            immutable_input_digests=immutable_input_digests,
            use_nailgun=immutable_input_digests,
            description=f"Generating Scala sources from {request.protocol_target.address}.",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
            env=jdk_setup.env,
            append_only_caches=jdk_setup.append_only_caches,
        ),
    )

    normalized_digest, source_root = await MultiGet(
        Get(Digest, RemovePrefix(result.output_digest, output_dir)),
        Get(SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)),
    )

    source_root_restored = (
        await Get(Snapshot, AddPrefix(normalized_digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, normalized_digest)
    )
    return GeneratedSources(source_root_restored)


class InjectScroogeDependencies(InjectDependenciesRequest):
    inject_for = ThriftDependenciesField


@rule
async def inject_scrooge_dependencies(
    _: InjectScroogeDependencies, scrooge: ScroogeSubsystem
) -> InjectedDependencies:
    addresses = await Get(Addresses, UnparsedAddressInputs, scrooge.runtime_dependencies)
    return InjectedDependencies(addresses)


@rule
async def generate_scrooge_lockfile_request(
    _: ScroogeToolLockfileSentinel,
    scrooge: ScroogeSubsystem,
) -> JvmToolLockfileRequest:
    return JvmToolLockfileRequest.from_tool(scrooge)


def rules():
    return [
        *collect_rules(),
        *additional_fields.rules(),
        UnionRule(GenerateSourcesRequest, GenerateScalaFromThriftRequest),
        UnionRule(InjectDependenciesRequest, InjectScroogeDependencies),
        UnionRule(JvmToolLockfileSentinel, ScroogeToolLockfileSentinel),
    ]
