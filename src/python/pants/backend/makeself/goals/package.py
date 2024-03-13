# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import itertools
import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional

from pants.backend.makeself.goals.run import MakeselfArchiveFieldSet
from pants.backend.makeself.subsystem import MakeselfTool
from pants.backend.shell.target_types import ShellSourceField
from pants.core.goals import package
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    EnvironmentAwarePackageRequest,
    PackageFieldSet,
)
from pants.core.target_types import FileSourceField
from pants.core.util_rules import source_files
from pants.core.util_rules.system_binaries import (
    AwkBinary,
    BasenameBinary,
    BinaryShims,
    BinaryShimsRequest,
    CatBinary,
    ChmodBinary,
    CksumBinary,
    CutBinary,
    DateBinary,
    DirnameBinary,
    DuBinary,
    ExprBinary,
    FindBinary,
    GzipBinary,
    RmBinary,
    SedBinary,
    ShBinary,
    SortBinary,
    TarBinary,
    TrBinary,
    WcBinary,
    XargsBinary,
)
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.native_engine import AddPrefix, Snapshot
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    HydratedSources,
    HydrateSourcesRequest,
    SourcesField,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreateMakeselfArchive:
    """
    Create Makeself archive with `await Get(ProcessResult, CreateMakeselfArchive(...))`.
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
    level: LogLevel = LogLevel.INFO
    cache_scope: Optional[ProcessCacheScope] = None
    timeout_seconds: Optional[int] = None


@rule
async def create_makeself_archive(
    request: CreateMakeselfArchive,
    makeself: MakeselfTool,
    awk: AwkBinary,
    basename: BasenameBinary,
    cat: CatBinary,
    date: DateBinary,
    dirname: DirnameBinary,
    du: DuBinary,
    expr: ExprBinary,
    find: FindBinary,
    gzip: GzipBinary,
    rm: RmBinary,
    sed: SedBinary,
    sh: ShBinary,
    sort: SortBinary,
    tar: TarBinary,
    wc: WcBinary,
    xargs: XargsBinary,
    tr: TrBinary,
    cksum: CksumBinary,
    cut: CutBinary,
    chmod: ChmodBinary,
) -> Process:
    shims = await Get(
        BinaryShims,
        BinaryShimsRequest(
            paths=(
                awk,
                basename,
                cat,
                date,
                dirname,
                du,
                expr,
                find,
                gzip,
                rm,
                sed,
                sh,
                sort,
                tar,
                wc,
                tr,
                cksum,
                cut,
                chmod,
                xargs,
            ),
            rationale="create makeself archive",
        ),
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

    package_targets, file_targets = await MultiGet(
        Get(Targets, UnparsedAddressInputs, field_set.packages.to_unparsed_address_inputs()),
        Get(Targets, UnparsedAddressInputs, field_set.files.to_unparsed_address_inputs()),
    )

    package_field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, package_targets)
    )
    packages = await MultiGet(
        Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
        for field_set in package_field_sets_per_target.field_sets
    )

    file_sources = await MultiGet(
        Get(
            HydratedSources,
            HydrateSourcesRequest(
                tgt.get(SourcesField),
                for_sources_types=(FileSourceField, ShellSourceField),
                enable_codegen=True,
            ),
        )
        for tgt in file_targets
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                *(package.digest for package in packages),
                *(sources.snapshot.digest for sources in file_sources),
            )
        ),
    )
    input_digest = await Get(Digest, AddPrefix(input_digest, archive_dir))

    output_path = PurePath(field_set.output_path.value_or_default(file_ending="run"))
    output_filename = output_path.name
    result = await Get(
        ProcessResult,
        CreateMakeselfArchive(
            archive_dir=archive_dir,
            file_name=output_filename,
            label=field_set.label.value or output_filename,
            startup_script=field_set.startup_script.value or (),
            args=field_set.args.value or (),
            input_digest=input_digest,
            output_filename=output_filename,
            description=f"Packaging makeself archive: {field_set.address}",
            level=LogLevel.DEBUG,
        ),
    )
    digest = await Get(Digest, AddPrefix(result.output_digest, str(output_path.parent)))
    snapshot = await Get(Snapshot, Digest, digest)
    assert len(snapshot.files) == 1, snapshot

    return BuiltPackage(
        snapshot.digest,
        artifacts=tuple(BuiltMakeselfArchiveArtifact.create(file) for file in snapshot.files),
    )


def rules():
    return [
        *collect_rules(),
        *package.rules(),
        *source_files.rules(),
        *MakeselfArchiveFieldSet.rules(),
        UnionRule(PackageFieldSet, MakeselfArchiveFieldSet),
    ]
