# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

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
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.system_binaries import BinaryShims
from pants.engine.fs import Digest
from pants.engine.process import Process
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.core.util_rules.system_binaries import create_binary_shims
from pants.engine.rules import implicitly
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
async def run_makeself_archive(request: RunMakeselfArchive) -> Process:
    shims = await create_binary_shims(
        **implicitly(
            MakeselfBinaryShimsRequest(
                extra_tools=request.extra_tools or (),
                rationale="run makeself archive",
            )
        )
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

    process = await run_makeself_archive(RunMakeselfArchive(
            exe=exe,
            input_digest=package.digest,
            description="Run makeself archive",
            extra_tools=field_set.tools.value or (),
    ))

    return RunRequest(
        digest=process.input_digest,
        args=(os.path.join("{chroot}", process.argv[0]),) + process.argv[1:],
        extra_env=process.env,
        immutable_input_digests=process.immutable_input_digests,
    )


def rules() -> Iterable[Rule]:
    return collect_rules()
