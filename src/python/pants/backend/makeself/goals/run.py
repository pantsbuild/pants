# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable, Tuple

from pants.backend.makeself.goals.package import MakeselfArchiveFieldSet, package_makeself_binary
from pants.backend.makeself.subsystem import RunMakeselfArchive
from pants.backend.makeself.system_binaries import MakeselfBinaryShimsRequest
from pants.core.goals.run import RunRequest
from pants.core.util_rules.system_binaries import create_binary_shims
from pants.engine.process import Process
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.util.logging import LogLevel


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


@rule
async def create_makeself_archive_run_request(field_set: MakeselfArchiveFieldSet) -> RunRequest:
    package = await package_makeself_binary(field_set)

    exe = package.artifacts[0].relpath
    if exe is None:
        raise RuntimeError(f"Invalid package artifact: {package}")

    process = await run_makeself_archive(
        RunMakeselfArchive(
            exe=exe,
            input_digest=package.digest,
            description="Run makeself archive",
            extra_tools=field_set.tools.value or (),
        )
    )

    return RunRequest(
        digest=process.input_digest,
        args=(os.path.join("{chroot}", process.argv[0]),) + process.argv[1:],
        extra_env=process.env,
        immutable_input_digests=process.immutable_input_digests,
    )


def rules() -> Iterable[Rule]:
    return collect_rules()
