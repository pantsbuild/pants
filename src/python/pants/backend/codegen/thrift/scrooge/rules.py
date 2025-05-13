# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass

from pants.backend.codegen.thrift.scrooge import additional_fields
from pants.backend.codegen.thrift.scrooge.additional_fields import ScroogeFinagleBoolField
from pants.backend.codegen.thrift.scrooge.subsystem import ScroogeSubsystem
from pants.backend.codegen.thrift.target_types import (
    ThriftSourceField,
    ThriftSourcesGeneratorTarget,
    ThriftSourceTarget,
)
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.fs import CreateDigest, Directory, MergeDigests, RemovePrefix, Snapshot
from pants.engine.internals.graph import resolve_target
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, digest_to_snapshot, merge_digests
from pants.engine.process import execute_process_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import TransitiveTargetsRequest, WrappedTargetRequest
from pants.engine.unions import UnionRule
from pants.jvm.goals import lockfile
from pants.jvm.jdk_rules import InternalJdk, JvmProcess
from pants.jvm.resolve.coursier_fetch import ToolClasspathRequest, materialize_classpath_for_tool
from pants.jvm.resolve.jvm_tool import GenerateJvmLockfileFromTool
from pants.jvm.target_types import PrefixedJvmJdkField, PrefixedJvmResolveField
from pants.source.source_root import SourceRootsRequest, get_source_roots
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GenerateScroogeThriftSourcesRequest:
    thrift_source_field: ThriftSourceField
    lang_id: str
    lang_name: str


@dataclass(frozen=True)
class GeneratedScroogeThriftSources:
    snapshot: Snapshot


@rule
async def generate_scrooge_thrift_sources(
    request: GenerateScroogeThriftSourcesRequest,
    jdk: InternalJdk,
    scrooge: ScroogeSubsystem,
) -> GeneratedScroogeThriftSources:
    output_dir = "_generated_files"
    toolcp_relpath = "__toolcp"

    lockfile_request = GenerateJvmLockfileFromTool.create(scrooge)
    (
        tool_classpath,
        transitive_targets,
        empty_output_dir_digest,
        wrapped_target,
    ) = await concurrently(
        materialize_classpath_for_tool(ToolClasspathRequest(lockfile=lockfile_request)),
        transitive_targets_get(
            TransitiveTargetsRequest([request.thrift_source_field.address]), **implicitly()
        ),
        create_digest(CreateDigest([Directory(output_dir)])),
        resolve_target(
            WrappedTargetRequest(
                request.thrift_source_field.address, description_of_origin="<infallible>"
            ),
            **implicitly(),
        ),
    )

    transitive_sources, target_sources = await concurrently(
        determine_source_files(
            SourceFilesRequest(
                tgt[ThriftSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ThriftSourceField)
            )
        ),
        determine_source_files(SourceFilesRequest([request.thrift_source_field])),
    )

    sources_roots = await get_source_roots(
        SourceRootsRequest.for_files(transitive_sources.snapshot.files)
    )
    deduped_source_root_paths = sorted({sr.path for sr in sources_roots.path_to_root.values()})

    input_digest = await merge_digests(
        MergeDigests(
            [
                transitive_sources.snapshot.digest,
                target_sources.snapshot.digest,
                empty_output_dir_digest,
            ]
        )
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

    result = await execute_process_or_raise(
        **implicitly(
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
                extra_jvm_options=scrooge.jvm_options,
                extra_immutable_input_digests=extra_immutable_input_digests,
                extra_nailgun_keys=extra_immutable_input_digests,
                description=f"Generating {request.lang_name} sources from {request.thrift_source_field.address}.",
                level=LogLevel.DEBUG,
                output_directories=(output_dir,),
            )
        )
    )

    output_snapshot = await digest_to_snapshot(
        **implicitly(RemovePrefix(result.output_digest, output_dir))
    )
    return GeneratedScroogeThriftSources(output_snapshot)


def rules():
    return [
        *collect_rules(),
        *additional_fields.rules(),
        *lockfile.rules(),
        UnionRule(ExportableTool, ScroogeSubsystem),
        ThriftSourceTarget.register_plugin_field(PrefixedJvmJdkField),
        ThriftSourcesGeneratorTarget.register_plugin_field(PrefixedJvmJdkField),
        ThriftSourceTarget.register_plugin_field(PrefixedJvmResolveField),
        ThriftSourcesGeneratorTarget.register_plugin_field(PrefixedJvmResolveField),
    ]
