# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import logging
import os
import shlex
import textwrap
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.util_rules import cgo_binaries, cgo_pkgconfig
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.cgo_binaries import CGoBinaryPathRequest
from pants.backend.go.util_rules.cgo_pkgconfig import (
    CGoPkgConfigFlagsRequest,
    CGoPkgConfigFlagsResult,
)
from pants.backend.go.util_rules.cgo_security import check_linker_flags
from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.core.util_rules.system_binaries import BashBinary, BinaryPath, BinaryPathTest
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.fs import (
    CreateDigest,
    DigestContents,
    DigestSubset,
    Directory,
    FileContent,
    PathGlobs,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel

_logger = logging.getLogger(__name__)


# Adapted from the Go toolchain.
# See generally https://github.com/golang/go/blob/master/src/cmd/go/internal/work/exec.go.
#
# Original copyright:
#   // Copyright 2011 The Go Authors. All rights reserved.
#   // Use of this source code is governed by a BSD-style
#   // license that can be found in the LICENSE file.


@dataclass(frozen=True)
class CGoCompileRequest(EngineAwareParameter):
    import_path: str
    pkg_name: str
    digest: Digest
    build_opts: GoBuildOptions
    dir_path: str
    cgo_files: tuple[str, ...]
    cgo_flags: CGoCompilerFlags
    c_files: tuple[str, ...] = ()
    cxx_files: tuple[str, ...] = ()
    objc_files: tuple[str, ...] = ()
    fortran_files: tuple[str, ...] = ()
    s_files: tuple[str, ...] = ()
    is_stdlib: bool = False
    transitive_prebuilt_object_files: tuple[Digest, frozenset[str]] | None = None

    def debug_hint(self) -> str | None:
        return self.import_path


@dataclass(frozen=True)
class CGoCompileResult:
    digest: Digest
    output_go_files: tuple[str, ...]
    output_obj_files: tuple[str, ...]

    # If True, then include the module sources in the same Digest as the package archive. This supports
    # cgo usages where the package wants to link with a static archive embedded in the module, for example,
    # https://github.com/confluentinc/confluent-kafka-go.
    include_module_sources_with_output: bool


@dataclass(frozen=True)
class CGoCompilerFlags:
    cflags: tuple[str, ...]
    cppflags: tuple[str, ...]
    cxxflags: tuple[str, ...]
    fflags: tuple[str, ...]
    ldflags: tuple[str, ...]
    pkg_config: tuple[str, ...]

    @classmethod
    def empty(cls) -> CGoCompilerFlags:
        return cls(
            cflags=(),
            cppflags=(),
            cxxflags=(),
            fflags=(),
            ldflags=(),
            pkg_config=(),
        )


@dataclass(frozen=True)
class CheckCompilerSupportsFlagRequest:
    cc: str
    flag: str


@dataclass(frozen=True)
class CheckCompilerSupportsOptionResult:
    supports_flag: bool


# Logic and comments in this rule come from `go` at:
# https://github.com/golang/go/blob/7eaad60737bc507596c56cec4951b089596ccc9e/src/cmd/go/internal/work/exec.go#L2570
@rule
async def check_compiler_supports_flag(
    request: CheckCompilerSupportsFlagRequest, goroot: GoRoot
) -> CheckCompilerSupportsOptionResult:
    input_digest = EMPTY_DIGEST
    tmp_file = "/dev/null"
    if goroot.goos == "windows":
        input_digest = await Get(Digest, CreateDigest([FileContent("grok.c", b"")]))
        tmp_file = "grok.c"

    # We used to write an empty C file, but that gets complicated with
    # go build -n. We tried using a file that does not exist, but that
    # fails on systems with GCC version 4.2.1; that is the last GPLv2
    # version of GCC, so some systems have frozen on it.
    # Now we pass an empty file on stdin, which should work at least for
    # GCC and clang.

    result = await Get(
        FallibleProcessResult,
        Process(
            [request.cc, request.flag, "-c", "-x", "c", "-", "-o", tmp_file],
            input_digest=input_digest,
            env={
                "LC_ALL": "C",
            },
            description=f"Check whether compiler `{request.cc}` for Cgo supports flag `{request.flag}`",
            level=LogLevel.DEBUG,
        ),
    )

    # GCC says "unrecognized command line option".
    # clang says "unknown argument".
    # Older versions of GCC say "unrecognised debug output level".
    # For -fsplit-stack GCC says "'-fsplit-stack' is not supported".
    combined_output = result.stdout + result.stderr
    supported = (
        b"unrecognized" not in combined_output
        and b"unknown" not in combined_output
        and b"unrecognised" not in combined_output
        and b"is not supported" not in combined_output
    )
    return CheckCompilerSupportsOptionResult(supported)


@dataclass(frozen=True)
class SetupCompilerCmdRequest:
    compiler: tuple[str, ...]
    include_dir: str


@dataclass(frozen=True)
class SetupCompilerCmdResult:
    args: tuple[str, ...]


# Logic and comments in this rule come from `go` toolchain.
# Note: Commented-out Go code remains in this function because it was not clear yet how to adapt that code.
def _gcc_arch_args(goroot: GoRoot) -> list[str]:
    goarch = goroot.goarch
    if goarch == "386":
        return ["-m32"]
    elif goarch == "amd64":
        if goroot.goos == "darwin":
            return ["-arch", "x86_64", "-m64"]
        return ["-m64"]
    elif goarch == "arm64":
        if goroot.goos == "darwin":
            return ["-arch", "arm64"]
    elif goarch == "arm":
        return ["-marm"]  # not thumb
    elif goarch == "s390x":
        return ["-m64", "-march=z196"]
    elif goarch in ("mips64", "mips64le"):
        args = ["-mabi=64"]
        # if cfg.GOMIPS64 == "hardfloat" {
        # return append(args, "-mhard-float")
        # } else if cfg.GOMIPS64 == "softfloat" {
        # return append(args, "-msoft-float")
        # }
        return args
    elif goarch in ("mips", "mipsle"):
        args = ["-mabi=32", "-march=mips32"]
        # if cfg.GOMIPS == "hardfloat" {
        #     return append(args, "-mhard-float", "-mfp32", "-mno-odd-spreg")
        # } else if cfg.GOMIPS == "softfloat" {
        #     return append(args, "-msoft-float")
        # }
        return args
    elif goarch == "ppc64":
        if goroot.goos == "aix":
            return ["-maix64"]
    return []


# Note: This function is adapted mostly from the Go toolchain. Comments are generally from the adapted
# function. Portions that did not make sense to adapt yet have been commented out.
@rule
async def setup_compiler_cmd(
    request: SetupCompilerCmdRequest, goroot: GoRoot
) -> SetupCompilerCmdResult:
    args = [*request.compiler, "-I", request.include_dir]

    # Definitely want -fPIC but on Windows gcc complains
    # "-fPIC ignored for target (all code is position independent)"
    if goroot.goos != "windows":
        args.append("-fPIC")
    args.extend(_gcc_arch_args(goroot))

    # gcc-4.5 and beyond require explicit "-pthread" flag
    # for multithreading with pthread library.
    # TODO: Disable this if cgo disabled?
    #   `go` code has conditional: if cfg.BuildContext.CgoEnabled
    #   but this file is cgo only
    if goroot.goos == "windows":
        args.append("-mthreads")
    else:
        args.append("-pthread")

    if goroot.goos == "aix":
        # mcmodel=large must always be enabled to allow large TOC.
        args.append("-mcmodel=large")

    # disable ASCII art in clang errors, if possible
    supports_no_caret_diagnostics = await Get(
        CheckCompilerSupportsOptionResult,
        CheckCompilerSupportsFlagRequest(request.compiler[0], "-fno-caret-diagnostics"),
    )
    if supports_no_caret_diagnostics.supports_flag:
        args.append("-fno-caret-diagnostics")
    # clang is too smart about command-line arguments
    supports_unused_arguments = await Get(
        CheckCompilerSupportsOptionResult,
        CheckCompilerSupportsFlagRequest(request.compiler[0], "-Qunused-arguments"),
    )
    if supports_unused_arguments.supports_flag:
        args.append("-Qunused-arguments")

    # disable word wrapping in error messages
    args.append("-fmessage-length=0")

    # Tell gcc not to include the work directory in object files.
    # if b.gccSupportsFlag(compiler, "-fdebug-prefix-map=a=b") {
    # if workdir == "" {
    # workdir = b.WorkDir
    # }
    # workdir = strings.TrimSuffix(workdir, string(filepath.Separator))
    # a = append(a, "-fdebug-prefix-map="+workdir+"=/tmp/go-build")
    # }

    # Tell gcc not to include flags in object files, which defeats the
    # point of -fdebug-prefix-map above.
    supports_no_record_gcc_switches = await Get(
        CheckCompilerSupportsOptionResult,
        CheckCompilerSupportsFlagRequest(request.compiler[0], "-gno-record-gcc-switches"),
    )
    if supports_no_record_gcc_switches.supports_flag:
        args.append("-gno-record-gcc-switches")

    # On OS X, some of the compilers behave as if -fno-common
    # is always set, and the Mach-O linker in 6l/8l assumes this.
    # See https://golang.org/issue/3253.
    if goroot.goos == "darwin" or goroot.goos == "ios":
        args.append("-fno-common")

    return SetupCompilerCmdResult(tuple(args))


@dataclass(frozen=True)
class CGoCompilerWrapperScript:
    digest: Digest


@rule
async def make_cgo_compile_wrapper_script() -> CGoCompilerWrapperScript:
    digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    path="wrapper",
                    content=textwrap.dedent(
                        """\
                sandbox_root="$(/bin/pwd)"
                args=("${@//__PANTS_SANDBOX_ROOT__/$sandbox_root}")
                exec "${args[@]}"
                """
                    ).encode(),
                    is_executable=True,
                )
            ]
        ),
    )
    return CGoCompilerWrapperScript(digest=digest)


async def _cc(
    binary_name: str,
    input_digest: Digest,
    dir_path: str,
    src_file: str,
    flags: Iterable[str],
    obj_file: str,
    description: str,
    golang_env_aware: GolangSubsystem.EnvironmentAware,
) -> Process:
    compiler_path, bash, wrapper_script = await MultiGet(
        Get(
            BinaryPath,
            CGoBinaryPathRequest(
                binary_name=binary_name,
                binary_path_test=BinaryPathTest(["--version"]),
            ),
        ),
        Get(BashBinary),
        Get(CGoCompilerWrapperScript),
    )
    compiler_args_result, env, input_digest = await MultiGet(
        Get(SetupCompilerCmdResult, SetupCompilerCmdRequest((compiler_path.path,), dir_path)),
        Get(
            EnvironmentVars,
            EnvironmentVarsRequest(golang_env_aware.env_vars_to_pass_to_subprocesses),
        ),
        Get(Digest, MergeDigests([input_digest, wrapper_script.digest])),
    )
    replaced_flags = _replace_srcdir_in_flags(flags, dir_path)
    args = [
        bash.path,
        "./wrapper",
        *compiler_args_result.args,
        *replaced_flags,
        "-o",
        obj_file,
        "-c",
        src_file,
    ]
    return Process(
        argv=args,
        env={"TERM": "dumb", **env},
        input_digest=input_digest,
        output_files=(obj_file,),
        description=description,
        level=LogLevel.DEBUG,
    )


async def _gccld(
    binary_name: str,
    input_digest: Digest,
    dir_path: str,
    outfile: str,
    flags: Iterable[str],
    objs: Iterable[str],
    description: str,
) -> FallibleProcessResult:
    compiler_path, bash, wrapper_script = await MultiGet(
        Get(
            BinaryPath,
            CGoBinaryPathRequest(
                binary_name=binary_name,
                binary_path_test=BinaryPathTest(["--version"]),
            ),
        ),
        Get(BashBinary),
        Get(CGoCompilerWrapperScript),
    )

    compiler_args_result, env, input_digest = await MultiGet(
        Get(SetupCompilerCmdResult, SetupCompilerCmdRequest((compiler_path.path,), dir_path)),
        Get(EnvironmentVars, EnvironmentVarsRequest(["PATH"])),
        Get(Digest, MergeDigests([input_digest, wrapper_script.digest])),
    )

    replaced_flags_in_compiler_args = _replace_srcdir_in_flags(compiler_args_result.args, dir_path)
    replaced_other_flags = _replace_srcdir_in_flags(flags, dir_path)

    args = [
        bash.path,
        "./wrapper",
        *replaced_flags_in_compiler_args,
        "-o",
        outfile,
        *objs,
        *replaced_other_flags,
    ]

    result = await Get(
        FallibleProcessResult,
        Process(
            argv=args,
            env={"TERM": "dumb", **env},
            input_digest=input_digest,
            output_files=(outfile,),
            description=description,
            level=LogLevel.DEBUG,
        ),
    )

    # TODO(#16828): Filter out output with irrelevant warnings just like `go` tool does.

    return result


@dataclass(frozen=True)
class _DynImportResult:
    digest: Digest
    dyn_out_go: str | None  # if not empty, is a new Go file to build as part of the package.
    dyn_out_obj: str | None  # if not empty, is a new file to add to the generated archive.
    use_external_link: bool


# From Go comments:
#   dynimport creates a Go source file named importGo containing
#   //go:cgo_import_dynamic directives for each symbol or library
#   dynamically imported by the object files outObj.
#   dynOutObj, if not empty, is a new file to add to the generated archive.'
#
# see https://github.com/golang/go/blob/f28fa952b5f81a63afd96c9c58dceb99cc7d1dbf/src/cmd/go/internal/work/exec.go#L3020
#
# Note: Commented-out Go code remains in this function because it was not clear yet how to adapt that code.
async def _dynimport(
    import_path: str,
    input_digest: Digest,
    obj_files: Iterable[str],
    dir_path: str,
    obj_dir_path: str,
    cflags: Iterable[str],
    ldflags: Iterable[str],
    pkg_name: str,
    goroot: GoRoot,
    import_go_path: str,
    golang_env_aware: GolangSubsystem.EnvironmentAware,
    use_cxx_linker: bool,
    transitive_prebuilt_objects_digest: Digest,
    transitive_prebuilt_objects: frozenset[str],
) -> _DynImportResult:
    cgo_main_compile_process = await _cc(
        binary_name=golang_env_aware.cgo_gcc_binary_name,
        input_digest=input_digest,
        dir_path=dir_path,
        src_file=os.path.join(obj_dir_path, "_cgo_main.c"),
        flags=cflags,
        obj_file=os.path.join(obj_dir_path, "_cgo_main.o"),
        description=f"Compile _cgo_main.c ({import_path})",
        golang_env_aware=golang_env_aware,
    )
    cgo_main_compile_result = await Get(ProcessResult, Process, cgo_main_compile_process)
    obj_digest = await Get(
        Digest,
        MergeDigests(
            [
                input_digest,
                cgo_main_compile_result.output_digest,
                transitive_prebuilt_objects_digest,
            ]
        ),
    )

    dynobj = os.path.join(obj_dir_path, "_cgo_.o")
    ldflags = list(ldflags)
    if (goroot.goarch == "arm" and goroot.goos == "linux") or goroot.goos == "android":
        if "-no-pie" not in ldflags:
            # we need to use -pie for Linux/ARM to get accurate imported sym (added in https://golang.org/cl/5989058)
            # this seems to be outdated, but we don't want to break existing builds depending on this (Issue 45940)
            ldflags.append("-pie")
        if "-pie" in ldflags and "-static" in ldflags:
            # -static -pie doesn't make sense, and causes link errors.
            # Issue 26197.
            ldflags = [arg for arg in ldflags if arg != "-static"]

    linker_binary_name = (
        golang_env_aware.cgo_gxx_binary_name
        if use_cxx_linker
        else golang_env_aware.cgo_gcc_binary_name
    )

    cgo_binary_link_result = await _gccld(
        binary_name=linker_binary_name,
        input_digest=obj_digest,
        dir_path=dir_path,
        outfile=dynobj,
        flags=ldflags,
        objs=[
            *obj_files,
            os.path.join(obj_dir_path, "_cgo_main.o"),
            *sorted(transitive_prebuilt_objects),
        ],
        description=f"Link _cgo_.o ({import_path})",
    )
    if cgo_binary_link_result.exit_code != 0:
        # From `go` source:
        #   We only need this information for internal linking.
        #   If this link fails, mark the object as requiring
        #   external linking. This link can fail for things like
        #   syso files that have unexpected dependencies.
        #   cmd/link explicitly looks for the name "dynimportfail".
        #   See issue #52863.
        _logger.info(
            f"cgo binary link failed:\n"
            f"stdout:\n{cgo_binary_link_result.stdout.decode()}\n"
            f"stderr:\n{cgo_binary_link_result.stderr.decode()}\n"
        )
        # return _DynImportResult(digest=EMPTY_DIGEST, dyn_out_go=None, dyn_out_obj=None, use_external_link=True)
        # If linking the binary for cgo fails, this is usually because the
        # object files reference external symbols that can't be resolved yet.
        # Since the binary is only produced to have its symbols read by the cgo
        # command, there is no harm in trying to build it allowing unresolved
        # symbols - the real link that happens at the end will fail if they
        # rightfully can't be resolved.
        if goroot.goos == "windows":
            # MinGW's linker doesn't seem to support --unresolved-symbols
            # and MSVC isn't supported at all.
            raise ValueError("link error - no workaround on Windows")
        elif goroot.goos in ("darwin", "ios"):
            allow_unresolved_symbols_ldflag = "-Wl,-undefined,dynamic_lookup"
        else:
            allow_unresolved_symbols_ldflag = "-Wl,--unresolved-symbols=ignore-all"
        # Print and return the original error if we can't link the binary with
        # the additional linker flags as they may simply be incorrect for the
        # particular compiler/linker pair and would obscure the true reason for
        # the failure of the original command.
        cgo_binary_link_result = await _gccld(
            binary_name=linker_binary_name,
            input_digest=obj_digest,
            dir_path=dir_path,
            outfile=dynobj,
            flags=[*ldflags, allow_unresolved_symbols_ldflag],
            objs=obj_files,
            description=f"Link _cgo_.o ({import_path})",
        )
        if cgo_binary_link_result.exit_code != 0:
            raise ValueError(
                f"cgo binary link failed:\n"
                f"stdout:\n{cgo_binary_link_result.stdout.decode()}\n"
                f"stderr:\n{cgo_binary_link_result.stderr.decode()}\n"
            )

    # cgo -dynimport
    dynimport_process_result = await Get(
        ProcessResult,
        GoSdkProcess(
            command=[
                "tool",
                "cgo",
                # record path to dynamic linker
                *(["-dynlinker"] if import_path == "runtime/cgo" else []),
                "-dynpackage",
                pkg_name,
                "-dynimport",
                dynobj,
                "-dynout",
                import_go_path,
            ],
            description="Gather cgo dynimport data.",
            env={"TERM": "dumb"},
            input_digest=cgo_binary_link_result.output_digest,
            output_files=(import_go_path,),
        ),
    )
    return _DynImportResult(
        digest=dynimport_process_result.output_digest,
        dyn_out_go=import_go_path,
        dyn_out_obj=None,
        use_external_link=False,
    )


# Note: Comments are mostly from the original function in Go toolchain sources.
def _check_link_args_in_content(src: bytes):
    cgo_ldflag_directive = b"//go:cgo_ldflag"
    idx = src.find(cgo_ldflag_directive)
    flags = []
    while idx >= 0:
        # We are looking at //go:cgo_ldflag.
        # Find start of line.
        start = src[:idx].rfind(b"\n")
        if start == -1:
            start = 0

        # Find end of line.
        end = src[idx:].find(b"\n")
        if end == -1:
            end = len(src)
        else:
            end += idx

        # Check for first line comment in line.
        # We don't worry about /* */ comments,
        # which normally won't appear in files
        # generated by cgo.
        comment_start = src[start:].find(b"//")
        comment_start += start
        # If that line comment is //go:cgo_ldflag,
        # it's a match.
        if src[comment_start:].startswith(cgo_ldflag_directive):
            # Pull out the flag, and unquote it.
            # This is what the compiler does.
            flag = src[idx + len(cgo_ldflag_directive) : end].decode()
            flag = flag.strip()
            flag = flag.strip('"')
            flags.append(flag)

        src = src[end:]
        idx = src.find(cgo_ldflag_directive)

    check_linker_flags(flags, "go:cgo_ldflag")


async def _ensure_only_allowed_link_args(
    digest: Digest, dir_path: str, go_files: Iterable[str]
) -> None:
    cgo_go_files = [
        os.path.join(dir_path, go_file) for go_file in go_files if go_file.startswith("_cgo_")
    ]
    digest_contents = await Get(
        DigestContents,
        DigestSubset(
            digest,
            PathGlobs(
                globs=cgo_go_files,
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin="cgo-related go_files",
            ),
        ),
    )

    for entry in digest_contents:
        _check_link_args_in_content(entry.content)


def _replace_srcdir_in_arg(flag: str, dir_path: str) -> str:
    if "${SRCDIR}" in flag:
        return flag.replace("${SRCDIR}", f"__PANTS_SANDBOX_ROOT__/{dir_path}")
    else:
        return flag


def _replace_srcdir_in_flags(flags: Iterable[str], dir_path: str) -> tuple[str, ...]:
    return tuple(_replace_srcdir_in_arg(flag, dir_path) for flag in flags)


@rule
async def cgo_compile_request(
    request: CGoCompileRequest, goroot: GoRoot, golang_env_aware: GolangSubsystem.EnvironmentAware
) -> CGoCompileResult:
    dir_path = request.dir_path if request.dir_path else "."

    obj_dir_path = (
        f"__go_stdlib_obj__/{request.import_path}" if os.path.isabs(dir_path) else dir_path
    )
    cgo_input_digest = request.digest
    if os.path.isabs(dir_path):
        mkdir_digest = await Get(Digest, CreateDigest([Directory(obj_dir_path)]))
        cgo_input_digest = await Get(Digest, MergeDigests([cgo_input_digest, mkdir_digest]))

    # Extract the cgo flags instance from the request so it can be updated as necessary.
    flags = request.cgo_flags

    # Prepend the default compiler options (`-g -O2`) before any package-specific options extracted from cgo
    # directives.
    flags = dataclasses.replace(
        flags,
        cflags=golang_env_aware.cgo_c_flags + flags.cflags,
        cxxflags=golang_env_aware.cgo_cxx_flags + flags.cxxflags,
        fflags=golang_env_aware.cgo_fortran_flags + flags.fflags,
        ldflags=golang_env_aware.cgo_linker_flags + flags.ldflags,
    )

    # Resolve pkg-config flags into compiler and linker flags.
    if request.cgo_flags.pkg_config:
        pkg_config_flags = await Get(
            CGoPkgConfigFlagsResult,
            CGoPkgConfigFlagsRequest(
                pkg_config_args=request.cgo_flags.pkg_config,
            ),
        )
        flags = dataclasses.replace(
            flags,
            cppflags=flags.cppflags + pkg_config_flags.cflags,
            ldflags=flags.ldflags + pkg_config_flags.ldflags,
        )

    # If compiling C++, then link against C++ standard library.
    if request.cxx_files:
        flags = dataclasses.replace(flags, ldflags=flags.ldflags + ("-lstdc++",))

    # If we are compiling Objective-C code, then we need to link against libobjc
    if request.objc_files:
        flags = dataclasses.replace(flags, ldflags=flags.ldflags + ("-lobjc",))

    # Likewise for Fortran, except there are many Fortran compilers.
    # Support gfortran out of the box and let others pass the correct link options
    # via CGO_LDFLAGS
    if request.fortran_files and "gfortran" in golang_env_aware.cgo_fortran_binary_name:
        flags = dataclasses.replace(flags, ldflags=flags.ldflags + ("-lgfortran",))

    if request.build_opts.with_msan:
        flags = dataclasses.replace(
            flags,
            cflags=flags.cflags + ("-fsanitize=memory",),
            ldflags=flags.ldflags + ("-fsanitize=memory",),
        )

    if request.build_opts.with_asan:
        flags = dataclasses.replace(
            flags,
            cflags=flags.cflags + ("-fsanitize=address",),
            ldflags=flags.ldflags + ("-fsanitize=address",),
        )

    # Allows including _cgo_export.h, as well as the user's .h files,
    # from .[ch] files in the package.
    flags = dataclasses.replace(flags, cflags=flags.cflags + ("-I", dir_path))

    # Replace `${SRCDIR}` in LDFLAGS with the path to the source directory within the sandbox.
    # From Go docs:
    #   When the cgo directives are parsed, any occurrence of the string ${SRCDIR} will be replaced by the
    #   absolute path to the directory containing the source file. This allows pre-compiled static libraries
    #   to be included in the package directory and linked properly. For example if package foo is in the
    #   directory /go/src/foo:
    flags = CGoCompilerFlags(
        cflags=_replace_srcdir_in_flags(flags.cflags, dir_path),
        cppflags=_replace_srcdir_in_flags(flags.cppflags, dir_path),
        cxxflags=_replace_srcdir_in_flags(flags.cxxflags, dir_path),
        fflags=_replace_srcdir_in_flags(flags.fflags, dir_path),
        ldflags=_replace_srcdir_in_flags(flags.ldflags, dir_path),
        pkg_config=flags.pkg_config,
    )

    go_files: list[str] = [os.path.join(obj_dir_path, "_cgo_gotypes.go")]
    gcc_files: list[str] = [
        os.path.join(obj_dir_path, "_cgo_export.c"),
        *(os.path.join(dir_path, c_file) for c_file in request.c_files),
        *(os.path.join(dir_path, s_file) for s_file in request.s_files),
    ]
    for cgo_file in request.cgo_files:
        cgo_file_path = PurePath(cgo_file)
        stem = cgo_file_path.stem
        go_files.append(os.path.join(obj_dir_path, f"{stem}.cgo1.go"))
        gcc_files.append(os.path.join(obj_dir_path, f"{stem}.cgo2.c"))

    # When building certain parts of the standard library, disable certain imports in generated code.
    maybe_disable_imports_flags: list[str] = []
    if request.is_stdlib and request.import_path == "runtime/cgo":
        maybe_disable_imports_flags.append("-import_runtime_cgo=false")
    if request.is_stdlib and request.import_path in (
        "runtime/race",
        "runtime/msan",
        "runtime/cgo",
        "runtime/asan",
    ):
        maybe_disable_imports_flags.append("-import_syscall=false")

    # Update CGO_LDFLAGS with the configured linker flags.
    #
    # From Go sources:
    #   These flags are recorded in the generated _cgo_gotypes.go file
    #   using //go:cgo_ldflag directives, the compiler records them in the
    #   object file for the package, and then the Go linker passes them
    #   along to the host linker. At this point in the code, cgoLDFLAGS
    #   consists of the original $CGO_LDFLAGS (unchecked) and all the
    #   flags put together from source code (checked).
    #
    # Note: Some packages, e.g. https://github.com/confluentinc/confluent-kafka-go, try to link a static archive
    # emedded in the module into the package archive. If so, mark this package so that the module sources are
    # included in the output digest for the build of this package. We assume that this is needed if an earlier
    # replacement of `${SRCDIR}` resulted in `__PANTS_SANDBOX_ROOT__` appearing in the flags. The
    # `__PANTS_SANDBOX_ROOT__` will be replaced by the external linker wrapper configured in `link.py`.
    cgo_env = {"CGO_ENABLED": "1", "TERM": "dumb"}
    include_module_sources_with_output = False
    if flags.ldflags:
        for arg in flags.ldflags:
            if "__PANTS_SANDBOX_ROOT__" in arg:
                include_module_sources_with_output = True
        cgo_env["CGO_LDFLAGS"] = " ".join([shlex.quote(arg) for arg in flags.ldflags])

    # Note: If Pants supported building C static or shared archives, then we would need to direct cgo here to
    # produce a header file via the `-exportheader` option. Not necessary since Pants does not support that.

    # Invoke cgo.
    cgo_result = await Get(
        ProcessResult,
        GoSdkProcess(
            [
                "tool",
                "cgo",
                "-objdir",
                obj_dir_path,
                "-importpath",
                request.import_path,
                *maybe_disable_imports_flags,
                # TODO(#16835): Add -trimpath option to remove sandbox paths from source paths embedded in files.
                # This means using `__PANTS_SANDBOX_ROOT__` support of `GoSdkProcess`.
                "--",
                *flags.cppflags,
                *flags.cflags,
                *(os.path.join(dir_path, f) for f in request.cgo_files),
            ],
            env=cgo_env,
            description=f"Generate Go and C files from CGo files ({request.import_path})",
            input_digest=cgo_input_digest,
            output_directories=(obj_dir_path,),
            replace_sandbox_root_in_args=True,
        ),
    )

    out_obj_files: list[str] = []
    oseq = 0
    compile_process_gets = []

    # C files
    cflags = [*flags.cppflags, *flags.cflags]
    for gcc_file in gcc_files:
        ofile = os.path.join(obj_dir_path, f"_x{oseq:03}.o")
        oseq = oseq + 1
        out_obj_files.append(ofile)

        compile_process = await _cc(
            binary_name=golang_env_aware.cgo_gcc_binary_name,
            input_digest=cgo_result.output_digest,
            dir_path=dir_path,
            src_file=gcc_file,
            flags=cflags,
            obj_file=ofile,
            description=f"Compile cgo source: {gcc_file}",
            golang_env_aware=golang_env_aware,
        )
        compile_process_gets.append(Get(ProcessResult, Process, compile_process))

    # C++ files
    cxxflags = [*flags.cppflags, *flags.cxxflags]
    for cxx_file in (os.path.join(dir_path, cxx_file) for cxx_file in request.cxx_files):
        ofile = os.path.join(obj_dir_path, f"_x{oseq:03}.o")
        oseq = oseq + 1
        out_obj_files.append(ofile)

        compile_process = await _cc(
            binary_name=golang_env_aware.cgo_gxx_binary_name,
            input_digest=cgo_result.output_digest,
            dir_path=dir_path,
            src_file=cxx_file,
            flags=cxxflags,
            obj_file=ofile,
            description=f"Compile cgo C++ source: {cxx_file}",
            golang_env_aware=golang_env_aware,
        )
        compile_process_gets.append(Get(ProcessResult, Process, compile_process))

    # Objective-C files
    for objc_file in (os.path.join(dir_path, objc_file) for objc_file in request.objc_files):
        ofile = os.path.join(obj_dir_path, f"_x{oseq:03}.o")
        oseq = oseq + 1
        out_obj_files.append(ofile)

        compile_process = await _cc(
            binary_name=golang_env_aware.cgo_gcc_binary_name,
            input_digest=cgo_result.output_digest,
            dir_path=dir_path,
            src_file=objc_file,
            flags=cflags,
            obj_file=ofile,
            description=f"Compile cgo Objective-C source: {objc_file}",
            golang_env_aware=golang_env_aware,
        )
        compile_process_gets.append(Get(ProcessResult, Process, compile_process))

    fflags = [*flags.cppflags, *flags.fflags]
    for fortran_file in (
        os.path.join(dir_path, fortran_file) for fortran_file in request.fortran_files
    ):
        ofile = os.path.join(obj_dir_path, f"_x{oseq:03}.o")
        oseq = oseq + 1
        out_obj_files.append(ofile)

        compile_process = await _cc(
            binary_name=golang_env_aware.cgo_fortran_binary_name,
            input_digest=cgo_result.output_digest,
            dir_path=dir_path,
            src_file=fortran_file,
            flags=fflags,
            obj_file=ofile,
            description=f"Compile cgo Fortran source: {fortran_file}",
            golang_env_aware=golang_env_aware,
        )
        compile_process_gets.append(Get(ProcessResult, Process, compile_process))

    # Dispatch all of the compilation requests.
    compile_results = await MultiGet(compile_process_gets)
    out_obj_files_digest = await Get(
        Digest, MergeDigests([r.output_digest for r in compile_results])
    )

    # Run dynimport process to create a Go source file named importGo containing
    # //go:cgo_import_dynamic directives for each symbol or library
    # dynamically imported by the object files outObj.
    dynimport_input_digest = await Get(
        Digest,
        MergeDigests(
            [
                cgo_result.output_digest,
                out_obj_files_digest,
            ]
        ),
    )
    transitive_prebuilt_objects_digest: Digest = EMPTY_DIGEST
    transitive_prebuilt_objects: frozenset[str] = frozenset()
    if request.transitive_prebuilt_object_files:
        transitive_prebuilt_objects_digest = request.transitive_prebuilt_object_files[0]
        transitive_prebuilt_objects = request.transitive_prebuilt_object_files[1]

    dynimport_result = await _dynimport(
        import_path=request.import_path,
        input_digest=dynimport_input_digest,
        dir_path=dir_path,
        obj_dir_path=obj_dir_path,
        obj_files=out_obj_files,
        cflags=cflags,
        ldflags=request.cgo_flags.ldflags,
        pkg_name=request.pkg_name,
        goroot=goroot,
        import_go_path=os.path.join(obj_dir_path, "_cgo_import.go"),
        golang_env_aware=golang_env_aware,
        use_cxx_linker=bool(request.cxx_files),
        transitive_prebuilt_objects_digest=transitive_prebuilt_objects_digest,
        transitive_prebuilt_objects=transitive_prebuilt_objects,
    )
    if dynimport_result.dyn_out_go:
        go_files.append(dynimport_result.dyn_out_go)
    if dynimport_result.dyn_out_obj:
        out_obj_files.append(dynimport_result.dyn_out_obj)

    # Double check the //go:cgo_ldflag comments in the generated files.
    # The compiler only permits such comments in files whose base name
    # starts with "_cgo_". Make sure that the comments in those files
    # are safe. This is a backstop against people somehow smuggling
    # such a comment into a file generated by cgo.
    await _ensure_only_allowed_link_args(cgo_result.output_digest, dir_path, go_files)

    output_digest = await Get(
        Digest,
        MergeDigests(
            [
                cgo_result.output_digest,
                out_obj_files_digest,
                dynimport_result.digest,
            ]
        ),
    )
    return CGoCompileResult(
        digest=output_digest,
        output_go_files=tuple(go_files),
        output_obj_files=tuple(out_obj_files),
        include_module_sources_with_output=include_module_sources_with_output,
    )


def rules():
    return (
        *collect_rules(),
        *cgo_binaries.rules(),
        *cgo_pkgconfig.rules(),
    )
