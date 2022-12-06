# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, GoSdkToolIDResult
from pants.engine.fs import CreateDigest, Digest, Directory, FileContent, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule


@dataclass(frozen=True)
class GenerateAssemblySymabisRequest:
    """Generate a `symabis` file with metadata about the assemnbly files for consumption by Go
    compiler.

    See https://github.com/bazelbuild/rules_go/issues/1893.
    """

    compilation_input: Digest
    s_files: tuple[str, ...]
    dir_path: str


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
    asm_header_path: str | None
    import_path: str


@dataclass(frozen=True)
class AssembleGoAssemblyFilesResult:
    assembly_outputs: tuple[tuple[str, Digest], ...]


@dataclass(frozen=True)
class FallibleAssembleGoAssemblyFilesResult:
    result: AssembleGoAssemblyFilesResult | None
    exit_code: int = 0
    stdout: str | None = None
    stderr: str | None = None


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
    obj_dir_path = PurePath(".", request.dir_path, "__obj__")
    symabis_path = str(obj_dir_path / "symabis")
    go_asm_h_digest, asm_tool_id, obj_dir_digest = await MultiGet(
        Get(Digest, CreateDigest([FileContent("go_asm.h", b"")])),
        Get(GoSdkToolIDResult, GoSdkToolIDRequest("asm")),
        Get(Digest, CreateDigest([Directory(str(obj_dir_path))])),
    )
    symabis_input_digest = await Get(
        Digest, MergeDigests([request.compilation_input, go_asm_h_digest, obj_dir_digest])
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
                symabis_path,
                "--",
                *(str(PurePath(".", request.dir_path, s_file)) for s_file in request.s_files),
            ),
            env={
                "__PANTS_GO_ASM_TOOL_ID": asm_tool_id.tool_id,
            },
            description=f"Generate symabis metadata for assembly files for {request.dir_path}",
            output_files=(symabis_path,),
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
    # On Go 1.19+, the import path must be supplied via the `-p` option to `go tool asm`.
    # See https://go.dev/doc/go1.19#assembler and
    # https://github.com/bazelbuild/rules_go/commit/cde7d7bc27a34547c014369790ddaa95b932d08d (Bazel rules_go).
    maybe_package_import_path_args = (
        ["-p", request.import_path] if goroot.is_compatible_version("1.19") else []
    )

    obj_dir_path = PurePath(".", request.dir_path, "__obj__")
    asm_tool_id, obj_dir_digest = await MultiGet(
        Get(GoSdkToolIDResult, GoSdkToolIDRequest("asm")),
        Get(Digest, CreateDigest([Directory(str(obj_dir_path))])),
    )

    input_digest = await Get(Digest, MergeDigests([request.input_digest, obj_dir_digest]))

    maybe_asm_header_path_args = (
        ["-I", str(PurePath(request.asm_header_path).parent)] if request.asm_header_path else []
    )

    def obj_output_path(s_file: str) -> str:
        return str(obj_dir_path / PurePath(s_file).with_suffix(".o"))

    assembly_results = await MultiGet(
        Get(
            FallibleProcessResult,
            GoSdkProcess(
                input_digest=input_digest,
                command=(
                    "tool",
                    "asm",
                    "-I",
                    os.path.join(goroot.path, "pkg", "include"),
                    *maybe_asm_header_path_args,
                    *maybe_package_import_path_args,
                    "-o",
                    obj_output_path(s_file),
                    str(os.path.normpath(PurePath(".", request.dir_path, s_file))),
                ),
                env={
                    "__PANTS_GO_ASM_TOOL_ID": asm_tool_id.tool_id,
                },
                description=f"Assemble {s_file} with Go",
                output_files=(obj_output_path(s_file),),
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
