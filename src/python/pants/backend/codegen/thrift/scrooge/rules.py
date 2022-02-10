# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.codegen.thrift.scrooge import additional_fields
from pants.backend.codegen.thrift.scrooge.additional_fields import ScroogeFinagleBoolField
from pants.backend.codegen.thrift.scrooge.subsystem import ScroogeSubsystem
from pants.backend.codegen.thrift.target_types import ThriftSourceField
from pants.build_graph.address import Address
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix, Snapshot
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest, WrappedTarget
from pants.engine.unions import UnionRule
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspath, ToolClasspathRequest
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.source.source_root import SourceRootsRequest, SourceRootsResult
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GenerateScroogeThriftSourcesRequest:
    thrift_source_field: ThriftSourceField
    lang_id: str
    lang_name: str


@dataclass(frozen=True)
class GeneratedScroogeThriftSources:
    snapshot: Snapshot


class ScroogeToolLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = ScroogeSubsystem.options_scope


@rule
async def generate_scrooge_thrift_sources(
    request: GenerateScroogeThriftSourcesRequest,
    jdk: InternalJdk,
    scrooge: ScroogeSubsystem,
) -> GeneratedScroogeThriftSources:
    output_dir = "_generated_files"
    toolcp_relpath = "__toolcp"

    lockfile_request = await Get(GenerateJvmLockfileFromTool, ScroogeToolLockfileSentinel())
    tool_classpath, transitive_targets, empty_output_dir_digest, wrapped_target = await MultiGet(
        Get(ToolClasspath, ToolClasspathRequest(lockfile=lockfile_request)),
        Get(TransitiveTargets, TransitiveTargetsRequest([request.thrift_source_field.address])),
        Get(Digest, CreateDigest([Directory(output_dir)])),
        Get(WrappedTarget, Address, request.thrift_source_field.address),
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
        Get(SourceFiles, SourceFilesRequest([request.thrift_source_field])),
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
    if wrapped_target.target[ScroogeFinagleBoolField].value:
        maybe_finagle_option = ["--finagle"]

    extra_immutable_input_digests = {
        toolcp_relpath: tool_classpath.digest,
    }

    result = await Get(
        ProcessResult,
        JvmProcess(
            jdk=jdk,
            classpath_entries=tool_classpath.classpath_entries(toolcp_relpath),
            argv=[
                "com.twitter.scrooge.Main",
                *maybe_include_paths,
                "--dest",
                output_dir,
                "--language",
                request.lang_id,
                *maybe_finagle_option,
                *target_sources.snapshot.files,
            ],
            input_digest=input_digest,
            extra_immutable_input_digests=extra_immutable_input_digests,
            extra_nailgun_keys=extra_immutable_input_digests,
            description=f"Generating {request.lang_name} sources from {request.thrift_source_field.address}.",
            level=LogLevel.DEBUG,
            output_directories=(output_dir,),
        ),
    )

    output_snapshot = await Get(Snapshot, RemovePrefix(result.output_digest, output_dir))
    return GeneratedScroogeThriftSources(output_snapshot)


@rule
def generate_scrooge_lockfile_request(
    _: ScroogeToolLockfileSentinel, scrooge: ScroogeSubsystem
) -> GenerateJvmLockfileFromTool:
    return GenerateJvmLockfileFromTool.create(scrooge)


def rules():
    return [
        *collect_rules(),
        *additional_fields.rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, ScroogeToolLockfileSentinel),
    ]
