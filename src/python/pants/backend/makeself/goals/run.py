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
    MakeselfArchiveToolsField,
    MakeselfArthiveLabelField,
)
from pants.backend.shell.subsystems.shell_setup import ShellSetup
from pants.backend.shell.util_rules.builtin import BASH_BUILTIN_COMMANDS
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.system_binaries import (
    AwkBinary,
    BasenameBinary,
    BashBinary,
    BinaryPathRequest,
    BinaryShims,
    BinaryShimsRequest,
    CatBinary,
    CksumBinary,
    CutBinary,
    DateBinary,
    DdBinary,
    DfBinary,
    DirnameBinary,
    ExprBinary,
    FindBinary,
    GzipBinary,
    HeadBinary,
    IdBinary,
    MkdirBinary,
    PwdBinary,
    RmBinary,
    SedBinary,
    TailBinary,
    TarBinary,
    TestBinary,
    WcBinary,
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
    extra_tools: Tuple[str, ...] = ()


@rule(desc="Run makeself archive", level=LogLevel.DEBUG)
async def run_makeself_archive(
    request: RunMakeselfArchive,
    shell_setup: ShellSetup.EnvironmentAware,
    awk: AwkBinary,
    basename: BasenameBinary,
    bash: BashBinary,
    cat: CatBinary,
    cksum: CksumBinary,
    cut: CutBinary,
    date: DateBinary,
    dd: DdBinary,
    df: DfBinary,
    dirname: DirnameBinary,
    expr: ExprBinary,
    find: FindBinary,
    gzip: GzipBinary,
    head: HeadBinary,
    id: IdBinary,
    mkdir: MkdirBinary,
    pwd: PwdBinary,
    rm: RmBinary,
    sed: SedBinary,
    tail: TailBinary,
    tar: TarBinary,
    test: TestBinary,
    wc: WcBinary,
) -> Process:
    shims = await Get(
        BinaryShims,
        BinaryShimsRequest(
            paths=(
                awk,
                basename,
                bash,
                cat,
                cksum,
                cut,
                date,
                dd,
                df,
                dirname,
                expr,
                find,
                gzip,
                head,
                id,
                mkdir,
                pwd,
                rm,
                sed,
                tail,
                tar,
                test,
                wc,
            ),
            requests=tuple(
                BinaryPathRequest(
                    binary_name=binary_name,
                    search_path=shell_setup.executable_search_path,
                )
                for binary_name in request.extra_tools
                if binary_name not in BASH_BUILTIN_COMMANDS
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
    tools: MakeselfArchiveToolsField


@rule
async def create_makeself_archive_run_request(field_set: MakeselfArchiveFieldSet) -> RunRequest:
    package = await Get(BuiltPackage, PackageFieldSet, field_set)

    exe = package.artifacts[0].relpath
    if exe is None:
        raise RuntimeError(f"Invalid package artifact: {package}")

    process = await Get(
        Process,
        RunMakeselfArchive(
            exe=exe,
            input_digest=package.digest,
            description="Run makeself archive",
            extra_tools=field_set.tools.value or (),
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
