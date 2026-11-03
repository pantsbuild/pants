# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from typing import Any

from pants.backend.codegen.protobuf.buf.config import find_buf_config_files
from pants.backend.codegen.protobuf.buf.skip_field import SkipBufLintField
from pants.backend.codegen.protobuf.buf.subsystem import BufSubsystem
from pants.backend.codegen.protobuf.target_types import (
    ProtobufDependenciesField,
    ProtobufSourceField,
)
from pants.core.goals.lint import LintResult, LintTargetsRequest, Partitions
from pants.core.util_rules import config_files
from pants.core.util_rules.adhoc_process_support import (
    ResolveRunnableDependenciesRequest,
    resolve_runnable_dependencies,
)
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.source_files import SourceFilesRequest
from pants.core.util_rules.stripped_source_files import strip_source_roots
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import MergeDigests
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.intrinsics import execute_process, merge_digests
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import FieldSet, Target, TransitiveTargetsRequest
from pants.util.logging import LogLevel
from pants.util.meta import classproperty
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class BufFieldSet(FieldSet):
    required_fields = (ProtobufSourceField,)

    sources: ProtobufSourceField
    dependencies: ProtobufDependenciesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipBufLintField).value


class BufLintRequest(LintTargetsRequest):
    field_set_type = BufFieldSet
    tool_subsystem = BufSubsystem  # type: ignore[assignment]

    @classproperty
    def tool_name(cls) -> str:
        return "buf lint"

    @classproperty
    def tool_id(cls) -> str:
        return "buf-lint"


@rule
async def partition_buf(
    request: BufLintRequest.PartitionRequest[BufFieldSet], buf: BufSubsystem
) -> Partitions[BufFieldSet, Any]:
    return Partitions() if buf.lint_skip else Partitions.single_partition(request.field_sets)


@rule(desc="Lint with buf lint", level=LogLevel.DEBUG)
async def run_buf(
    request: BufLintRequest.Batch[BufFieldSet, Any], buf: BufSubsystem, platform: Platform
) -> LintResult:
    transitive_targets = await transitive_targets_get(
        TransitiveTargetsRequest(field_set.address for field_set in request.elements),
        **implicitly(),
    )

    all_stripped_sources_request = strip_source_roots(
        **implicitly(
            SourceFilesRequest(
                tgt[ProtobufSourceField]
                for tgt in transitive_targets.closure
                if tgt.has_field(ProtobufSourceField)
            )
        )
    )
    target_stripped_sources_request = strip_source_roots(
        **implicitly(
            SourceFilesRequest(
                (field_set.sources for field_set in request.elements),
                for_sources_types=(ProtobufSourceField,),
                enable_codegen=True,
            )
        )
    )

    download_buf_get = download_external_tool(buf.get_request(platform))

    config_files_get = find_buf_config_files(buf)

    plugins_get = resolve_runnable_dependencies(
        ResolveRunnableDependenciesRequest(
            UnparsedAddressInputs(
                buf.plugins,
                owning_address=None,
                description_of_origin=f"the `[{BufSubsystem.options_scope}].plugins` option",
            )
        ),
        **implicitly(),
    )

    (
        target_sources_stripped,
        all_sources_stripped,
        downloaded_buf,
        config_files,
        resolved_plugins,
    ) = await concurrently(
        target_stripped_sources_request,
        all_stripped_sources_request,
        download_buf_get,
        config_files_get,
        plugins_get,
    )

    input_digest = await merge_digests(
        MergeDigests(
            (
                target_sources_stripped.snapshot.digest,
                all_sources_stripped.snapshot.digest,
                downloaded_buf.digest,
                config_files.snapshot.digest,
                resolved_plugins.digest,
            )
        )
    )

    config_arg = ["--config", buf.config] if buf.config else []

    # Buf resolves a bare `plugins: - plugin: <name>` entry off PATH, and refuses to exec a binary
    # found via a relative PATH entry.
    plugins = resolved_plugins.runnable_dependencies
    env = {"PATH": f"{{chroot}}/{plugins.path_component}", **plugins.extra_env} if plugins else {}

    process_result = await execute_process(
        Process(
            argv=[
                downloaded_buf.exe,
                "lint",
                *config_arg,
                *buf.lint_args,
                "--path",
                ",".join(target_sources_stripped.snapshot.files),
            ],
            input_digest=input_digest,
            immutable_input_digests=plugins.immutable_input_digests if plugins else None,
            append_only_caches=plugins.append_only_caches if plugins else None,
            env=env,
            description=f"Run buf lint on {pluralize(len(request.elements), 'file')}.",
            level=LogLevel.DEBUG,
        ),
        **implicitly(),
    )
    return LintResult.create(request, process_result)


def rules():
    return [
        *collect_rules(),
        *adhoc_process_support_rules(),
        *config_files.rules(),
        *BufLintRequest.rules(),
    ]
