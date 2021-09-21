# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule


@dataclass(frozen=True)
class AssemblyPreCompilation:
    merged_compilation_input_digest: Digest
    assembly_digests: tuple[Digest, ...]
    EXTRA_COMPILATION_ARGS = ("-symabis", "./symabis")


@dataclass(frozen=True)
class AssemblyPreCompilationRequest:
    """Add a `symabis` file for consumption by Go compiler and assemble all `.s` files.

    See https://github.com/bazelbuild/rules_go/issues/1893.
    """

    compilation_input: Digest
    s_files: tuple[str, ...]
    source_files_subpath: str


@dataclass(frozen=True)
class AssemblyPostCompilation:
    merged_output_digest: Digest


@dataclass(frozen=True)
class AssemblyPostCompilationRequest:
    """Link the assembly_digests into the compilation_result."""

    compilation_result: Digest
    assembly_digests: tuple[Digest, ...]
    s_files: tuple[str, ...]
    source_files_subpath: str


@rule
async def setup_assembly_pre_compilation(
    request: AssemblyPreCompilationRequest,
) -> AssemblyPreCompilation:
    # From Go tooling comments:
    #
    #   Supply an empty go_asm.h as if the compiler had been run. -symabis parsing is lax enough
    #   that we don't need the actual definitions that would appear in go_asm.h.
    #
    # See https://go-review.googlesource.com/c/go/+/146999/8/src/cmd/go/internal/work/gc.go
    go_asm_h_digest = await Get(Digest, CreateDigest([FileContent("go_asm.h", b"")]))
    symabis_input_digest = await Get(
        Digest, MergeDigests([request.compilation_input, go_asm_h_digest])
    )
    symabis_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=symabis_input_digest,
            command=(
                "tool",
                "asm",
                "-I",
                "go/pkg/include",
                "-gensymabis",
                "-o",
                "symabis",
                "--",
                *(f"./{request.source_files_subpath}/{name}" for name in request.s_files),
            ),
            description="Generate symabis metadata for assembly files.",
            output_files=("symabis",),
        ),
    )
    merged = await Get(
        Digest,
        MergeDigests([request.compilation_input, symabis_result.output_digest]),
    )

    assembly_results = await MultiGet(
        Get(
            ProcessResult,
            GoSdkProcess(
                input_digest=request.compilation_input,
                command=(
                    "tool",
                    "asm",
                    "-I",
                    "go/pkg/include",
                    "-o",
                    f"./{request.source_files_subpath}/{PurePath(s_file).with_suffix('.o')}",
                    f"./{request.source_files_subpath}/{s_file}",
                ),
                description=f"Assemble {s_file}",
                output_files=(
                    f"./{request.source_files_subpath}/{PurePath(s_file).with_suffix('.o')}",
                ),
            ),
        )
        for s_file in request.s_files
    )
    return AssemblyPreCompilation(
        merged, tuple(result.output_digest for result in assembly_results)
    )


@rule
async def link_assembly_post_compilation(
    request: AssemblyPostCompilationRequest,
) -> AssemblyPostCompilation:
    merged_digest = await Get(
        Digest, MergeDigests([request.compilation_result, *request.assembly_digests])
    )
    pack_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=merged_digest,
            command=(
                "tool",
                "pack",
                "r",
                "__pkg__.a",
                *(
                    f"./{request.source_files_subpath}/{PurePath(name).with_suffix('.o')}"
                    for name in request.s_files
                ),
            ),
            description="Link assembly files to Go package archive.",
            output_files=("__pkg__.a",),
        ),
    )
    return AssemblyPostCompilation(pack_result.output_digest)


def rules():
    return collect_rules()
