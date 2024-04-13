# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, GoSdkToolIDResult
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule


@dataclass(frozen=True)
class GenerateAssemblySymabisRequest:
    """Generate a `symabis` file with metadata about the assembly files for consumption by Go
    compiler.

    See https://github.com/bazelbuild/rules_go/issues/1893.
    """

    compilation_input: Digest
    s_files: tuple[str, ...]
    import_path: str
    dir_path: str
    extra_assembler_flags: tuple[str, ...]


@dataclass(frozen=True)
class GenerateAssemblySymabisResult:
    symabis_digest: Digest
    symabis_path: str


@dataclass(frozen=True)
class FallibleGenerateAssemblySymabisResult:
    result: GenerateAssemblySymabisResult | None
    exit_code: int = 0
    stdout: str | None = None
    stderr: str | None = None


@dataclass(frozen=True)
class AssembleGoAssemblyFilesRequest:
    """Assemble Go assembly files to object files."""

    input_digest: Digest
    s_files: tuple[str, ...]
    dir_path: str
    import_path: str
    extra_assembler_flags: tuple[str, ...]


@dataclass(frozen=True)
class AssembleGoAssemblyFilesResult:
    assembly_outputs: tuple[tuple[str, Digest], ...]


@dataclass(frozen=True)
class FallibleAssembleGoAssemblyFilesResult:
    result: AssembleGoAssemblyFilesResult | None
    exit_code: int = 0
    stdout: str | None = None
    stderr: str | None = None


# Adapted from https://github.com/golang/go/blob/cb07765045aed5104a3df31507564ac99e6ddce8/src/cmd/go/internal/work/gc.go#L358-L410
#
# Note: Architecture-specific flags have not been adapted nor the flags added when compiling Go SDK packages
# themselves.
def _asm_args(
    import_path: str, dir_path: str, goroot: GoRoot, extra_flags: Iterable[str]
) -> tuple[str, ...]:
    # On Go 1.19+, the import path must be supplied via the `-p` option to `go tool asm`.
    # See https://go.dev/doc/go1.19#assembler and
    # https://github.com/bazelbuild/rules_go/commit/cde7d7bc27a34547c014369790ddaa95b932d08d (Bazel rules_go).
    maybe_package_import_path_args = (
        ["-p", import_path] if goroot.is_compatible_version("1.19") else []
    )

    # Add special argument if assembling files in certain packages in the standard library.
    # See:
    # - https://github.com/golang/go/blob/245e95dfabd77f337373bf2d6bb47cd353ad8d74/src/cmd/go/internal/work/gc.go#L370-L372
    # - https://github.com/golang/go/blob/245e95dfabd77f337373bf2d6bb47cd353ad8d74/src/cmd/internal/objabi/path.go#L43-L67
    # From Go 1.22+ this flag has been removed, since we're already passing the package path, asm can make that determination,
    # and there's no need to pass the flag anymore.
    # See:
    # - https://cs.opensource.google/go/go/+/72946ae8674a295e7485982fe57c65c7142b2c14
    maybe_assembling_stdlib_runtime_args = (
        ["-compiling-runtime"]
        if not goroot.is_compatible_version("1.22")
        and (
            import_path in ("runtime", "reflect", "syscall", "internal/bytealg")
            or import_path.startswith("runtime/internal")
        )
        else []
    )

    return (
        *maybe_package_import_path_args,
        "-trimpath",
        "__PANTS_SANDBOX_ROOT__",
        "-I",
        f"__PANTS_SANDBOX_ROOT__/{dir_path}",
        # Add -I pkg/GOOS_GOARCH so #include "textflag.h" works in .s files.
        "-I",
        os.path.join(goroot.path, "pkg", "include"),
        "-D",
        f"GOOS_{goroot.goos}",
        "-D",
        f"GOARCH_{goroot.goarch}",
        *maybe_assembling_stdlib_runtime_args,
        *extra_flags,
    )


@rule
async def generate_go_assembly_symabisfile(
    request: GenerateAssemblySymabisRequest,
    goroot: GoRoot,
) -> FallibleGenerateAssemblySymabisResult:
    # From Go tooling comments:
    #
    #   Supply an empty go_asm.h as if the compiler had been run. -symabis parsing is lax enough
    #   that we don't need the actual definitions that would appear in go_asm.h.
    #
    # See https://go-review.googlesource.com/c/go/+/146999/8/src/cmd/go/internal/work/gc.go
    if os.path.isabs(request.dir_path):
        symabis_path = "symabis"
    else:
        symabis_path = os.path.join(request.dir_path, "symabis")
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
                *_asm_args(
                    import_path=request.import_path,
                    dir_path=request.dir_path,
                    goroot=goroot,
                    extra_flags=request.extra_assembler_flags,
                ),
                "-gensymabis",
                "-o",
                symabis_path,
                "--",
                *(str(PurePath(request.dir_path, s_file)) for s_file in request.s_files),
            ),
            env={
                "__PANTS_GO_ASM_TOOL_ID": asm_tool_id.tool_id,
            },
            description=f"Generate symabis metadata for assembly files for {request.dir_path}",
            output_files=(symabis_path,),
            replace_sandbox_root_in_args=True,
        ),
    )
    if symabis_result.exit_code != 0:
        return FallibleGenerateAssemblySymabisResult(
            None, symabis_result.exit_code, symabis_result.stderr.decode("utf-8")
        )

    return FallibleGenerateAssemblySymabisResult(
        result=GenerateAssemblySymabisResult(
            symabis_digest=symabis_result.output_digest,
            symabis_path=symabis_path,
        ),
    )


@rule
async def assemble_go_assembly_files(
    request: AssembleGoAssemblyFilesRequest,
    goroot: GoRoot,
) -> FallibleAssembleGoAssemblyFilesResult:
    asm_tool_id = await Get(GoSdkToolIDResult, GoSdkToolIDRequest("asm"))

    def obj_output_path(s_file: str) -> str:
        if os.path.isabs(request.dir_path):
            return str(PurePath(s_file).with_suffix(".o"))
        else:
            return str(request.dir_path / PurePath(s_file).with_suffix(".o"))

    assembly_results = await MultiGet(
        Get(
            FallibleProcessResult,
            GoSdkProcess(
                input_digest=request.input_digest,
                command=(
                    "tool",
                    "asm",
                    *_asm_args(
                        import_path=request.import_path,
                        dir_path=request.dir_path,
                        goroot=goroot,
                        extra_flags=request.extra_assembler_flags,
                    ),
                    "-o",
                    obj_output_path(s_file),
                    str(os.path.normpath(PurePath(request.dir_path, s_file))),
                ),
                env={
                    "__PANTS_GO_ASM_TOOL_ID": asm_tool_id.tool_id,
                },
                description=f"Assemble {s_file} with Go",
                output_files=(obj_output_path(s_file),),
                replace_sandbox_root_in_args=True,
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
        return FallibleAssembleGoAssemblyFilesResult(None, exit_code, stdout, stderr)

    assembly_outputs = tuple(
        (obj_output_path(s_file), result.output_digest)
        for s_file, result in zip(request.s_files, assembly_results)
    )

    return FallibleAssembleGoAssemblyFilesResult(
        AssembleGoAssemblyFilesResult(
            assembly_outputs=assembly_outputs,
        )
    )


def rules():
    return collect_rules()
