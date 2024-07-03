# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional, Tuple

from pants.backend.makeself.subsystem import MakeselfTool
from pants.backend.makeself.system_binaries import MakeselfBinaryShimsRequest
from pants.backend.makeself.target_types import (
    MakeselfArchiveArgsField,
    MakeselfArchiveFilesField,
    MakeselfArchiveOutputPathField,
    MakeselfArchivePackagesField,
    MakeselfArchiveStartupScriptField,
    MakeselfArchiveToolsField,
    MakeselfArthiveLabelField,
)
from pants.backend.shell.target_types import ShellSourceField
from pants.core.goals import package
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    EnvironmentAwarePackageRequest,
    PackageFieldSet,
    environment_aware_package,
)
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior
from pants.core.target_types import FileSourceField
from pants.core.util_rules import source_files
from pants.core.util_rules.system_binaries import create_binary_shims
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.graph import find_valid_field_sets, hydrate_sources, resolve_targets
from pants.engine.internals.native_engine import AddPrefix
from pants.engine.intrinsics import (
    add_prefix_request_to_digest,
    digest_to_snapshot,
    merge_digests_request_to_digest,
)
from pants.engine.process import Process, ProcessCacheScope, fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import FieldSetsPerTargetRequest, HydrateSourcesRequest, SourcesField
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MakeselfArchiveFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (MakeselfArchiveStartupScriptField,)
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    startup_script: MakeselfArchiveStartupScriptField
    label: MakeselfArthiveLabelField
    files: MakeselfArchiveFilesField
    packages: MakeselfArchivePackagesField
    output_path: MakeselfArchiveOutputPathField
    args: MakeselfArchiveArgsField
    tools: MakeselfArchiveToolsField


@dataclass(frozen=True)
class CreateMakeselfArchive:
    """Create Makeself archive with `await Get(ProcessResult, CreateMakeselfArchive(...))`.

    See docs for the options [here](https://github.com/megastep/makeself/tree/release-2.5.0#usage).
    """

    args: tuple[str, ...]
    archive_dir: str
    file_name: str
    label: str
    startup_script: tuple[str, ...]
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    output_filename: str
    extra_tools: Optional[Tuple[str, ...]] = None
    level: LogLevel = LogLevel.INFO
    cache_scope: Optional[ProcessCacheScope] = None
    timeout_seconds: Optional[int] = None


@rule
async def create_makeself_archive(
    request: CreateMakeselfArchive,
    makeself: MakeselfTool,
) -> Process:
    shims = await create_binary_shims(
        **implicitly(
            MakeselfBinaryShimsRequest(
                extra_tools=request.extra_tools or (),
                rationale="create makeself archive",
            )
        )
    )

    tooldir = "__makeself"
    argv = (
        os.path.join(tooldir, makeself.exe),
        *request.args,
        request.archive_dir,
        request.file_name,
        request.label,
        *request.startup_script,
    )

    process = Process(
        argv,
        input_digest=request.input_digest,
        immutable_input_digests={
            tooldir: makeself.digest,
            **shims.immutable_input_digests,
        },
        env={"PATH": shims.path_component},
        description=request.description,
        level=request.level,
        append_only_caches={},
        output_files=(request.output_filename,),
        cache_scope=request.cache_scope or ProcessCacheScope.SUCCESSFUL,
        timeout_seconds=request.timeout_seconds,
    )
    return process


@dataclass(frozen=True)
class BuiltMakeselfArchiveArtifact(BuiltPackageArtifact):
    @classmethod
    def create(cls, relpath: str) -> "BuiltMakeselfArchiveArtifact":
        return cls(
            relpath=relpath,
            extra_log_lines=(f"Built Makeself binary: {relpath}",),
        )


@rule
async def package_makeself_binary(field_set: MakeselfArchiveFieldSet) -> BuiltPackage:
    archive_dir = "__archive"

    package_targets, file_targets = await concurrently(
        resolve_targets(
            **implicitly({field_set.packages.to_unparsed_address_inputs(): UnparsedAddressInputs})
        ),
        resolve_targets(
            **implicitly({field_set.files.to_unparsed_address_inputs(): UnparsedAddressInputs})
        ),
    )

    package_field_sets_per_target = await find_valid_field_sets(
        FieldSetsPerTargetRequest(PackageFieldSet, package_targets), **implicitly()
    )
    packages = await concurrently(
        environment_aware_package(EnvironmentAwarePackageRequest(field_set))
        for field_set in package_field_sets_per_target.field_sets
    )

    file_sources = await concurrently(
        hydrate_sources(
            HydrateSourcesRequest(
                tgt.get(SourcesField),
                for_sources_types=(FileSourceField, ShellSourceField),
                enable_codegen=True,
            ),
            **implicitly(),
        )
        for tgt in file_targets
    )

    input_digest = await merge_digests_request_to_digest(
        MergeDigests(
            (
                *(package.digest for package in packages),
                *(sources.snapshot.digest for sources in file_sources),
            )
        )
    )
    input_digest = await add_prefix_request_to_digest(AddPrefix(input_digest, archive_dir))

    output_path = PurePath(field_set.output_path.value_or_default(file_ending="run"))
    output_filename = output_path.name
    result = await fallible_to_exec_result_or_raise(
        **implicitly(
            CreateMakeselfArchive(
                archive_dir=archive_dir,
                file_name=output_filename,
                label=field_set.label.value or output_filename,
                startup_script=field_set.startup_script.value or (),
                args=field_set.args.value or (),
                input_digest=input_digest,
                output_filename=output_filename,
                extra_tools=field_set.tools.value or (),
                description=f"Packaging makeself archive: {field_set.address}",
                level=LogLevel.DEBUG,
            )
        )
    )
    digest = await add_prefix_request_to_digest(
        AddPrefix(result.output_digest, str(output_path.parent))
    )
    snapshot = await digest_to_snapshot(digest)
    assert len(snapshot.files) == 1, snapshot

    return BuiltPackage(
        snapshot.digest,
        artifacts=tuple(BuiltMakeselfArchiveArtifact.create(file) for file in snapshot.files),
    )


def rules():
    return (
        *collect_rules(),
        *package.rules(),
        *source_files.rules(),
        *MakeselfArchiveFieldSet.rules(),
        UnionRule(PackageFieldSet, MakeselfArchiveFieldSet),
    )
