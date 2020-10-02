# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.util_rules.pex import Pex
from pants.core.util_rules.archive import UnzipBinary
from pants.engine.fs import Digest, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class ExtractedPexDistributions:
    digest: Digest
    wheel_directory_paths: Tuple[str, ...]


@rule
async def extract_distributions(pex: Pex, unzip_binary: UnzipBinary) -> ExtractedPexDistributions:
    # We only unzip the `.deps` folder to avoid unnecessary work. Note that this will cause the
    # process to fail if there is no `.deps` folder, so we need to use `FallibleProcessResult`.
    argv = (*unzip_binary.extract_archive_argv(archive_path=pex.name, output_dir="."), ".deps/*")
    unzipped_pex = await Get(
        FallibleProcessResult,
        Process(
            argv=argv,
            input_digest=pex.digest,
            output_directories=(".deps",),
            description=f"Unzip {pex.name} to determine its distributions",
            level=LogLevel.DEBUG,
        ),
    )
    snapshot = await Get(Snapshot, Digest, unzipped_pex.output_digest)
    directory_paths = tuple(sorted(d for d in snapshot.dirs if d.endswith(".whl")))
    return ExtractedPexDistributions(snapshot.digest, directory_paths)


def rules():
    return collect_rules()
