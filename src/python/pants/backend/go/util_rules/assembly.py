# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.subsystems.golang import GoRoot
from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, GoSdkToolIDResult
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule


@dataclass(frozen=True)
class FallibleAssemblyPreCompilation:
    result: AssemblyPreCompilation | None
    exit_code: int = 0
    stdout: str | None = None
    stderr: str | None = None


@dataclass(frozen=True)
class AssemblyPreCompilation:
    merged_compilation_input_digest: Digest
    assembly_digests: tuple[Digest, ...]


@dataclass(frozen=True)
class AssemblyPreCompilationRequest:
    """Add a `symabis` file for consumption by Go compiler and assemble all `.s` files.

    See https://github.com/bazelbuild/rules_go/issues/1893.
    """

    compilation_input: Digest
    s_files: tuple[str, ...]
    dir_path: str
    import_path: str


@dataclass(frozen=True)
class AssemblyPostCompilation:
    result: FallibleProcessResult
    merged_output_digest: Digest | None


@dataclass(frozen=True)
class AssemblyPostCompilationRequest:
    """Link the assembly_digests into the compilation_result."""

    compilation_result: Digest
    assembly_digests: tuple[Digest, ...]
    s_files: tuple[str, ...]
    dir_path: str


@rule
async def setup_assembly_pre_compilation(
    request: AssemblyPreCompilationRequest,
    goroot: GoRoot,
) -> FallibleAssemblyPreCompilation:
    # From Go tooling comments:
    #
    #   Supply an empty go_asm.h as if the compiler had been run. -symabis parsing is lax enough
    #   that we don't need the actual definitions that would appear in go_asm.h.
    #
    # See https://go-review.googlesource.com/c/go/+/146999/8/src/cmd/go/internal/work/gc.go
    go_asm_h_digest, asm_tool_id = await MultiGet(
        Get(Digest, CreateDigest([FileContent("go_asm.h", b"")])),
        Get(GoSdkToolIDResult, GoSdkToolIDRequest("asm")),
    )
    symabis_input_digest = await Get(
        Digest, MergeDigests([request.compilation_input, go_asm_h_digest])
    )
    symabis_result = await Get(
        FallibleProcessResult,
        GoSdkProcess(
            input_digest=symabis_input_digest,
            command=(
                "tool",
                "asm",
                "-I",
                os.path.join(goroot.path, "pkg", "include"),
                "-gensymabis",
                "-o",
                "symabis",
                "--",
                *(f"./{request.dir_path}/{name}" for name in request.s_files),
            ),
            env={
                "__PANTS_GO_ASM_TOOL_ID": asm_tool_id.tool_id,
            },
            description=f"Generate symabis metadata for assembly files for {request.dir_path}",
            output_files=("symabis",),
        ),
    )
    if symabis_result.exit_code != 0:
        return FallibleAssemblyPreCompilation(
            None, symabis_result.exit_code, symabis_result.stderr.decode("utf-8")
        )

    merged = await Get(
        Digest,
        MergeDigests([request.compilation_input, symabis_result.output_digest]),
    )

    # On Go 1.19+, the import path must be supplied via the `-p` option to `go tool asm`.
    # See https://go.dev/doc/go1.19#assembler and
    # https://github.com/bazelbuild/rules_go/commit/cde7d7bc27a34547c014369790ddaa95b932d08d (Bazel rules_go).
    maybe_package_path_args = (
        ["-p", request.import_path] if goroot.is_compatible_version("1.19") else []
    )

    assembly_results = await MultiGet(
        Get(
            FallibleProcessResult,
            GoSdkProcess(
                input_digest=request.compilation_input,
                command=(
                    "tool",
                    "asm",
                    "-I",
                    os.path.join(goroot.path, "pkg", "include"),
                    *maybe_package_path_args,
                    "-o",
                    f"./{request.dir_path}/{PurePath(s_file).with_suffix('.o')}",
                    f"./{request.dir_path}/{s_file}",
                ),
                env={
                    "__PANTS_GO_ASM_TOOL_ID": asm_tool_id.tool_id,
                },
                description=f"Assemble {s_file} with Go",
                output_files=(f"./{request.dir_path}/{PurePath(s_file).with_suffix('.o')}",),
            ),
        )
        for s_file in request.s_files
    )
    exit_code = max(result.exit_code for result in assembly_results)
    if exit_code != 0:
        stdout = "\n\n".join(
            result.stdout.decode("utf-8") for result in assembly_results if result.stdout
        )
        stderr = "\n\n".join(
            result.stderr.decode("utf-8") for result in assembly_results if result.stderr
        )
        return FallibleAssemblyPreCompilation(None, exit_code, stdout, stderr)

    return FallibleAssemblyPreCompilation(
        AssemblyPreCompilation(merged, tuple(result.output_digest for result in assembly_results))
    )


@rule
async def link_assembly_post_compilation(
    request: AssemblyPostCompilationRequest,
) -> AssemblyPostCompilation:
    merged_digest, asm_tool_id = await MultiGet(
        Get(Digest, MergeDigests([request.compilation_result, *request.assembly_digests])),
        # Use `go tool asm` tool ID since `go tool pack` does not have a version argument.
        Get(GoSdkToolIDResult, GoSdkToolIDRequest("asm")),
    )
    pack_result = await Get(
        FallibleProcessResult,
        GoSdkProcess(
            input_digest=merged_digest,
            command=(
                "tool",
                "pack",
                "r",
                "__pkg__.a",
                *(
                    f"./{request.dir_path}/{PurePath(name).with_suffix('.o')}"
                    for name in request.s_files
                ),
            ),
            env={
                "__PANTS_GO_ASM_TOOL_ID": asm_tool_id.tool_id,
            },
            description=f"Link assembly files to Go package archive for {request.dir_path}",
            output_files=("__pkg__.a",),
        ),
    )
    return AssemblyPostCompilation(
        pack_result, pack_result.output_digest if pack_result.exit_code == 0 else None
    )


def rules():
    return collect_rules()
