# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.fs import Digest
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule


@dataclass(frozen=True)
class CompileGoSourcesRequest:
    """Compile Go sources into the package archive __pkg__.a."""

    # The `Digest` containing the input Go source files and input packages.
    digest: Digest

    # Paths to each source file to compile.
    sources: tuple[str, ...]

    # The import path for the package being compiled.
    import_path: str

    # Description to use for the compilation.
    description: str

    # Import configuration
    import_config_path: str | None = None

    # Optional symabis file to use.
    symabis_path: str | None = None


@dataclass(frozen=True)
class CompiledGoSources:
    """Output from compiling Go sources.

    The package archive is called __pkg__.a.
    """

    output_digest: Digest


@rule
async def compile_go_sources(request: CompileGoSourcesRequest) -> CompiledGoSources:
    args = [
        "tool",
        "compile",
        "-p",
        request.import_path,
    ]

    if request.import_config_path:
        args.extend(["-importcfg", request.import_config_path])

    if request.symabis_path:
        args.extend(["-symabis", request.symabis_path])

    args.extend(["-pack", "-o", "__pkg__.a", "--", *request.sources])

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=request.digest,
            command=tuple(args),
            description=request.description,
            output_files=("__pkg__.a",),
        ),
    )

    return CompiledGoSources(output_digest=result.output_digest)


def rules():
    return collect_rules()
