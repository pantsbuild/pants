# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pants.backend.python.util_rules import pex_cli
from pants.backend.python.util_rules.pex import CompletePlatforms, Pex, PexPlatforms
from pants.backend.python.util_rules.pex_cli import PexCliProcess
from pants.engine.fs import Digest
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule


class PexVenvLayout(Enum):
    VENV = "venv"
    FLAT = "flat"
    FLAT_ZIPPED = "flat-zipped"


@dataclass(frozen=True)
class PexVenvRequest:
    pex: Pex
    layout: PexVenvLayout
    output_path: Path
    description: str

    platforms: PexPlatforms = PexPlatforms()
    complete_platforms: CompletePlatforms = CompletePlatforms()
    prefix: None | str = None
    collisions_ok: bool = False


@dataclass(frozen=True)
class PexVenv:
    digest: Digest
    path: Path


@rule
async def pex_venv(request: PexVenvRequest) -> PexVenv:
    # TODO: create the output with a fixed name and then rename
    # (https://github.com/pantsbuild/pants/issues/15102)
    if request.layout is PexVenvLayout.FLAT_ZIPPED:
        # --layout=flat-zipped takes --dest-dir=foo and zips it up to `foo.zip`, so we cannot
        # directly control the full path until we do a rename
        if request.output_path.suffix != ".zip":
            raise ValueError(
                f"layout=FLAT_ZIPPED requires output_path to end in '.zip', but found output_path='{request.output_path}' ending in {request.output_path.suffix!r}"
            )
        dest_dir = request.output_path.with_suffix("")
        output_files = [str(request.output_path)]
        output_directories = []
    else:
        dest_dir = request.output_path
        output_files = []
        output_directories = [str(request.output_path)]

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                request.pex.digest,
                request.complete_platforms.digest,
            ]
        ),
    )

    result = await Get(
        ProcessResult,
        PexCliProcess(
            subcommand=("venv", "create"),
            extra_args=(
                f"--dest-dir={dest_dir}",
                f"--pex-repository={request.pex.name}",
                f"--layout={request.layout.value}",
                *((f"--prefix={request.prefix}",) if request.prefix is not None else ()),
                *(("--collisions-ok",) if request.collisions_ok else ()),
                # NB. Specifying more than one of these args doesn't make sense for `venv
                # create`. Incorrect usage will be surfaced as a subprocess failure.
                *request.platforms.generate_pex_arg_list(),
                *request.complete_platforms.generate_pex_arg_list(),
            ),
            additional_input_digest=input_digest,
            output_files=output_files,
            output_directories=output_directories,
            description=request.description,
        ),
    )

    return PexVenv(digest=result.output_digest, path=request.output_path)


def rules():
    return [*collect_rules(), *pex_cli.rules()]
