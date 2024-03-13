# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.makeself.target_types import (
    MakeselfArchiveArgsField,
    MakeselfArchiveFilesField,
    MakeselfArchiveOutputPathField,
    MakeselfArchivePackagesField,
    MakeselfArchiveStartupScriptField,
    MakeselfArthiveLabelField,
)
from pants.core.goals.package import BuiltPackage, OutputPathField, PackageFieldSet
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.system_binaries import (
    AwkBinary,
    Base64Binary,
    BasenameBinary,
    BashBinary,
    BinaryShims,
    BinaryShimsRequest,
    Bzip2Binary,
    CatBinary,
    CutBinary,
    DateBinary,
    DdBinary,
    DfBinary,
    DirnameBinary,
    ExprBinary,
    FindBinary,
    GpgBinary,
    GzipBinary,
    HeadBinary,
    IdBinary,
    Md5sumBinary,
    MkdirBinary,
    PwdBinary,
    RmBinary,
    SedBinary,
    ShasumBinary,
    TailBinary,
    TarBinary,
    TestBinary,
    WcBinary,
    XzBinary,
    ZstdBinary,
)
from pants.engine.fs import Digest
from pants.engine.process import Process
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class RunMakeselfArchive:
    exe: str
    input_digest: Digest
    description: str
    level: LogLevel = LogLevel.INFO
    output_directory: Optional[str] = None
    extra_args: Optional[Tuple[str, ...]] = None


@rule(desc="Run makeself archive", level=LogLevel.DEBUG)
async def run_makeself_archive(
    request: RunMakeselfArchive,
    awk: AwkBinary,
    base64: Base64Binary,
    basename: BasenameBinary,
    bash: BashBinary,
    bzip2: Bzip2Binary,
    cat: CatBinary,
    cut: CutBinary,
    date: DateBinary,
    dd: DdBinary,
    df: DfBinary,
    dirname: DirnameBinary,
    expr: ExprBinary,
    find: FindBinary,
    gpg: GpgBinary,
    gzip: GzipBinary,
    head: HeadBinary,
    id: IdBinary,
    md5sum: Md5sumBinary,
    mkdir: MkdirBinary,
    pwd: PwdBinary,
    rm: RmBinary,
    sed: SedBinary,
    shasum: ShasumBinary,
    tail: TailBinary,
    tar: TarBinary,
    test: TestBinary,
    wc: WcBinary,
    xz: XzBinary,
    zstd: ZstdBinary,
) -> Process:
    shims = await Get(
        BinaryShims,
        BinaryShimsRequest(
            paths=(
                awk,
                base64,
                basename,
                bash,
                bzip2,
                cat,
                cut,
                date,
                dd,
                df,
                dirname,
                expr,
                find,
                gpg,
                gzip,
                head,
                id,
                md5sum,
                mkdir,
                pwd,
                rm,
                sed,
                shasum,
                tail,
                tar,
                test,
                wc,
                xz,
                zstd,
            ),
            rationale="run makeself archive",
        ),
    )
    output_directories = []
    argv: Tuple[str, ...] = (request.exe,)

    if output_directory := request.output_directory:
        output_directories = [output_directory]
        argv += ("--target", request.output_directory)

    return Process(
        argv=argv + (request.extra_args or ()),
        input_digest=request.input_digest,
        immutable_input_digests=shims.immutable_input_digests,
        output_directories=output_directories,
        description=request.description,
        level=request.level,
        env={"PATH": shims.path_component},
    )


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


@rule
async def create_makeself_archive_run_request(field_set: MakeselfArchiveFieldSet) -> RunRequest:
    package = await Get(BuiltPackage, PackageFieldSet, field_set)

    exe = package.artifacts[0].relpath
    assert exe is not None, package
    process = await Get(
        Process,
        RunMakeselfArchive(
            exe=exe,
            input_digest=package.digest,
            description="Run makeself archive",
        ),
    )

    return RunRequest(
        digest=process.input_digest,
        args=(os.path.join("{chroot}", process.argv[0]),) + process.argv[1:],
        extra_env=process.env,
        immutable_input_digests=process.immutable_input_digests,
    )


def rules():
    return collect_rules()
