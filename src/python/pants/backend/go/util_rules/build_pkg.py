# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import hashlib
import os.path
from collections import deque
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Mapping

from pants.backend.go.util_rules import cgo, coverage
from pants.backend.go.util_rules.assembly import (
    AssembleGoAssemblyFilesRequest,
    FallibleAssembleGoAssemblyFilesResult,
    FallibleGenerateAssemblySymabisResult,
    GenerateAssemblySymabisRequest,
)
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.cgo import CGoCompileRequest, CGoCompileResult, CGoCompilerFlags
from pants.backend.go.util_rules.coverage import (
    ApplyCodeCoverageRequest,
    ApplyCodeCoverageResult,
    BuiltGoPackageCodeCoverageMetadata,
    FileCodeCoverageMetadata,
)
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.import_config import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, GoSdkToolIDResult
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestEntries,
    DigestSubset,
    FileContent,
    FileEntry,
    MergeDigests,
    PathGlobs,
)
from pants.engine.process import FallibleProcessResult, Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.resources import read_resource
from pants.util.strutil import path_safe


class BuildGoPackageRequest(EngineAwareParameter):
    def __init__(
        self,
        *,
        import_path: str,
        pkg_name: str,
        digest: Digest,
        dir_path: str,
        build_opts: GoBuildOptions,
        go_files: tuple[str, ...],
        s_files: tuple[str, ...],
        direct_dependencies: tuple[BuildGoPackageRequest, ...],
        import_map: Mapping[str, str] | None = None,
        minimum_go_version: str | None,
        for_tests: bool = False,
        embed_config: EmbedConfig | None = None,
        with_coverage: bool = False,
        cgo_files: tuple[str, ...] = (),
        cgo_flags: CGoCompilerFlags | None = None,
        c_files: tuple[str, ...] = (),
        header_files: tuple[str, ...] = (),
        cxx_files: tuple[str, ...] = (),
        objc_files: tuple[str, ...] = (),
        fortran_files: tuple[str, ...] = (),
        prebuilt_object_files: tuple[str, ...] = (),
        pkg_specific_compiler_flags: tuple[str, ...] = (),
        pkg_specific_assembler_flags: tuple[str, ...] = (),
        is_stdlib: bool = False,
    ) -> None:
        """Build a package and its dependencies as `__pkg__.a` files.

        Instances of this class form a structure-shared DAG, and so a hashcode is pre-computed for
        the recursive portion.
        """

        if with_coverage and build_opts.coverage_config is None:
            raise ValueError(
                "BuildGoPackageRequest.with_coverage is set but BuildGoPackageRequest.build_opts.coverage_config is None!"
            )

        self.import_path = import_path
        self.pkg_name = pkg_name
        self.digest = digest
        self.dir_path = dir_path
        self.build_opts = build_opts
        self.go_files = go_files
        self.s_files = s_files
        self.direct_dependencies = direct_dependencies
        self.import_map = FrozenDict(import_map or {})
        self.minimum_go_version = minimum_go_version
        self.for_tests = for_tests
        self.embed_config = embed_config
        self.with_coverage = with_coverage
        self.cgo_files = cgo_files
        self.cgo_flags = cgo_flags
        self.c_files = c_files
        self.header_files = header_files
        self.cxx_files = cxx_files
        self.objc_files = objc_files
        self.fortran_files = fortran_files
        self.prebuilt_object_files = prebuilt_object_files
        self.pkg_specific_compiler_flags = pkg_specific_compiler_flags
        self.pkg_specific_assembler_flags = pkg_specific_assembler_flags
        self.is_stdlib = is_stdlib
        self._hashcode = hash(
            (
                self.import_path,
                self.pkg_name,
                self.digest,
                self.dir_path,
                self.build_opts,
                self.go_files,
                self.s_files,
                self.direct_dependencies,
                self.import_map,
                self.minimum_go_version,
                self.for_tests,
                self.embed_config,
                self.with_coverage,
                self.cgo_files,
                self.cgo_flags,
                self.c_files,
                self.header_files,
                self.cxx_files,
                self.objc_files,
                self.fortran_files,
                self.prebuilt_object_files,
                self.pkg_specific_compiler_flags,
                self.pkg_specific_assembler_flags,
                self.is_stdlib,
            )
        )

    def __repr__(self) -> str:
        # NB: We must override the default `__repr__` so that `direct_dependencies` does not
        # traverse into transitive dependencies, which was pathologically slow.
        return (
            f"{self.__class__}("
            f"import_path={repr(self.import_path)}, "
            f"pkg_name={self.pkg_name}, "
            f"digest={self.digest}, "
            f"dir_path={self.dir_path}, "
            f"build_opts={self.build_opts}, "
            f"go_files={self.go_files}, "
            f"s_files={self.s_files}, "
            f"direct_dependencies={[dep.import_path for dep in self.direct_dependencies]}, "
            f"import_map={self.import_map}, "
            f"minimum_go_version={self.minimum_go_version}, "
            f"for_tests={self.for_tests}, "
            f"embed_config={self.embed_config}, "
            f"with_coverage={self.with_coverage}, "
            f"cgo_files={self.cgo_files}, "
            f"cgo_flags={self.cgo_flags}, "
            f"c_files={self.c_files}, "
            f"header_files={self.header_files}, "
            f"cxx_files={self.cxx_files}, "
            f"objc_files={self.objc_files}, "
            f"fortran_files={self.fortran_files}, "
            f"prebuilt_object_files={self.prebuilt_object_files}, "
            f"pkg_specific_compiler_flags={self.pkg_specific_compiler_flags}, "
            f"pkg_specific_assembler_flags={self.pkg_specific_assembler_flags}, "
            f"is_stdlib={self.is_stdlib}"
            ")"
        )

    def __hash__(self) -> int:
        return self._hashcode

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return NotImplemented
        return (
            self._hashcode == other._hashcode
            and self.import_path == other.import_path
            and self.pkg_name == other.pkg_name
            and self.digest == other.digest
            and self.dir_path == other.dir_path
            and self.build_opts == other.build_opts
            and self.import_map == other.import_map
            and self.go_files == other.go_files
            and self.s_files == other.s_files
            and self.minimum_go_version == other.minimum_go_version
            and self.for_tests == other.for_tests
            and self.embed_config == other.embed_config
            and self.with_coverage == other.with_coverage
            and self.cgo_files == other.cgo_files
            and self.cgo_flags == other.cgo_flags
            and self.c_files == other.c_files
            and self.header_files == other.header_files
            and self.cxx_files == other.cxx_files
            and self.objc_files == other.objc_files
            and self.fortran_files == other.fortran_files
            and self.prebuilt_object_files == other.prebuilt_object_files
            and self.pkg_specific_compiler_flags == other.pkg_specific_compiler_flags
            and self.pkg_specific_assembler_flags == other.pkg_specific_assembler_flags
            and self.is_stdlib == other.is_stdlib
            # TODO: Use a recursive memoized __eq__ if this ever shows up in profiles.
            and self.direct_dependencies == other.direct_dependencies
        )

    def debug_hint(self) -> str | None:
        return self.import_path


@dataclass(frozen=True)
class FallibleBuildGoPackageRequest(EngineAwareParameter, EngineAwareReturnType):
    """Request to build a package, but fallible if determining the request metadata failed.

    When creating "synthetic" packages, use `GoPackageRequest` directly. This type is only intended
    for determining the package metadata of user code, which may fail to be analyzed.
    """

    request: BuildGoPackageRequest | None
    import_path: str
    exit_code: int = 0
    stderr: str | None = None
    dependency_failed: bool = False

    def level(self) -> LogLevel:
        return (
            LogLevel.ERROR if self.exit_code != 0 and not self.dependency_failed else LogLevel.DEBUG
        )

    def message(self) -> str:
        message = self.import_path
        message += (
            " succeeded." if self.exit_code == 0 else f" failed (exit code {self.exit_code})."
        )
        if self.stderr:
            message += f"\n{self.stderr}"
        return message

    def cacheable(self) -> bool:
        # Failed compile outputs should be re-rendered in every run.
        return self.exit_code == 0


@dataclass(frozen=True)
class FallibleBuiltGoPackage(EngineAwareReturnType):
    """Fallible version of `BuiltGoPackage` with error details."""

    output: BuiltGoPackage | None
    import_path: str
    exit_code: int = 0
    stdout: str | None = None
    stderr: str | None = None
    dependency_failed: bool = False

    def level(self) -> LogLevel:
        return (
            LogLevel.ERROR if self.exit_code != 0 and not self.dependency_failed else LogLevel.DEBUG
        )

    def message(self) -> str:
        message = self.import_path
        message += (
            " succeeded." if self.exit_code == 0 else f" failed (exit code {self.exit_code})."
        )
        if self.stdout:
            message += f"\n{self.stdout}"
        if self.stderr:
            message += f"\n{self.stderr}"
        return message

    def cacheable(self) -> bool:
        # Failed compile outputs should be re-rendered in every run.
        return self.exit_code == 0


@dataclass(frozen=True)
class BuiltGoPackage:
    """A package and its dependencies compiled as `__pkg__.a` files.

    The packages are arranged into `__pkgs__/{path_safe(import_path)}/__pkg__.a`.
    """

    digest: Digest
    import_paths_to_pkg_a_files: FrozenDict[str, str]
    coverage_metadata: BuiltGoPackageCodeCoverageMetadata | None = None


@dataclass(frozen=True)
class RenderEmbedConfigRequest:
    embed_config: EmbedConfig | None


@dataclass(frozen=True)
class RenderedEmbedConfig:
    digest: Digest
    PATH = "./embedcfg"


@dataclass(frozen=True)
class GoCompileActionIdRequest:
    build_request: BuildGoPackageRequest


@dataclass(frozen=True)
class GoCompileActionIdResult:
    action_id: str


# TODO(#16831): Merge this rule helper and the AssemblyPostCompilationRequest.
async def _add_objects_to_archive(
    input_digest: Digest,
    pkg_archive_path: str,
    obj_file_paths: Iterable[str],
) -> ProcessResult:
    # Use `go tool asm` tool ID since `go tool pack` does not have a version argument.
    asm_tool_id = await Get(GoSdkToolIDResult, GoSdkToolIDRequest("asm"))
    pack_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=(
                "tool",
                "pack",
                "r",
                pkg_archive_path,
                *obj_file_paths,
            ),
            env={
                "__PANTS_GO_ASM_TOOL_ID": asm_tool_id.tool_id,
            },
            description="Link objects to Go package archive",
            output_files=(pkg_archive_path,),
        ),
    )
    return pack_result


@dataclass(frozen=True)
class SetupAsmCheckBinary:
    digest: Digest
    path: str


# Due to the bootstrap problem, the asm check binary cannot use the `LoadedGoBinaryRequest` rules since
# those rules call back into this `build_pkg` package. Instead, just invoke `go build` directly which is fine
# since the asm check binary only uses the standard library.
@rule
async def setup_golang_asm_check_binary() -> SetupAsmCheckBinary:
    src_file = "asm_check.go"
    content = read_resource("pants.backend.go.go_sources.asm_check", src_file)
    if not content:
        raise AssertionError(f"Unable to find resource for `{src_file}`.")

    sources_digest = await Get(Digest, CreateDigest([FileContent(src_file, content)]))

    binary_name = "__go_asm_check__"
    compile_result = await Get(
        ProcessResult,
        GoSdkProcess(
            command=("build", "-o", binary_name, src_file),
            input_digest=sources_digest,
            output_files=(binary_name,),
            env={"CGO_ENABLED": "0"},
            description="Build Go assembly check binary",
        ),
    )

    return SetupAsmCheckBinary(compile_result.output_digest, f"./{binary_name}")


# Check whether the given files looks like they could be Golang-format assembly language files.
@dataclass(frozen=True)
class CheckForGolangAssemblyRequest:
    digest: Digest
    dir_path: str
    s_files: tuple[str, ...]


@dataclass(frozen=True)
class CheckForGolangAssemblyResult:
    maybe_golang_assembly: bool


@rule
async def check_for_golang_assembly(
    request: CheckForGolangAssemblyRequest,
    asm_check_setup: SetupAsmCheckBinary,
) -> CheckForGolangAssemblyResult:
    """Return true if any of the given `s_files` look like it could be a Golang-format assembly
    language file.

    This is used by the cgo rules as a heuristic to determine if the user is passing Golang assembly
    format instead of gcc assembly format.
    """
    input_digest = await Get(Digest, MergeDigests([request.digest, asm_check_setup.digest]))
    result = await Get(
        ProcessResult,
        Process(
            argv=(
                asm_check_setup.path,
                *(os.path.join(request.dir_path, s_file) for s_file in request.s_files),
            ),
            input_digest=input_digest,
            level=LogLevel.DEBUG,
            description="Check whether assembly language sources are in Go format",
        ),
    )
    return CheckForGolangAssemblyResult(len(result.stdout) > 0)


# Copy header files to names which use platform independent names. For example, defs_linux_amd64.h
# becomes defs_GOOS_GOARCH.h.
#
# See https://github.com/golang/go/blob/1c05968c9a5d6432fc6f30196528f8f37287dd3d/src/cmd/go/internal/work/exec.go#L867-L892
# for particulars.
async def _maybe_copy_headers_to_platform_independent_names(
    input_digest: Digest,
    dir_path: str,
    header_files: tuple[str, ...],
    goroot: GoRoot,
) -> Digest | None:
    goos_goarch = f"_{goroot.goos}_{goroot.goarch}"
    goos = f"_{goroot.goos}"
    goarch = f"_{goroot.goarch}"

    digest_entries = await Get(DigestEntries, Digest, input_digest)
    digest_entries_by_path: dict[str, FileEntry] = {
        entry.path: entry for entry in digest_entries if isinstance(entry, FileEntry)
    }

    new_digest_entries: list[FileEntry] = []
    for header_file in header_files:
        header_file_path = PurePath(dir_path, header_file)

        entry = digest_entries_by_path.get(str(header_file_path))
        if not entry:
            continue

        stem = header_file_path.stem
        new_stem: str | None = None
        if stem.endswith(goos_goarch):
            new_stem = stem[0 : -len(goos_goarch)] + "_GOOS_GOARCH"
        elif stem.endswith(goos):
            new_stem = stem[0 : -len(goos)] + "_GOOS"
        elif stem.endswith(goarch):
            new_stem = stem[0 : -len(goarch)] + "_GOARCH"

        if new_stem:
            new_header_file_path = PurePath(dir_path, f"{new_stem}{header_file_path.suffix}")
            new_digest_entries.append(dataclasses.replace(entry, path=str(new_header_file_path)))

    if new_digest_entries:
        digest = await Get(Digest, CreateDigest(new_digest_entries))
        return digest
    else:
        return None


# Gather transitive prebuilt object files for Cgo. Traverse the provided dependencies and lifts `.syso`
# object files into a single `Digest`.
async def _gather_transitive_prebuilt_object_files(
    build_request: BuildGoPackageRequest,
) -> tuple[Digest, frozenset[str]]:
    prebuilt_objects: list[tuple[Digest, list[str]]] = []

    queue: deque[BuildGoPackageRequest] = deque([build_request])
    seen: set[BuildGoPackageRequest] = {build_request}
    while queue:
        pkg = queue.popleft()
        unseen = [dd for dd in build_request.direct_dependencies if dd not in seen]
        queue.extend(unseen)
        seen.update(unseen)
        if pkg.prebuilt_object_files:
            prebuilt_objects.append(
                (
                    pkg.digest,
                    [
                        os.path.join(pkg.dir_path, obj_file)
                        for obj_file in pkg.prebuilt_object_files
                    ],
                )
            )

    object_digest = await Get(Digest, MergeDigests([digest for digest, _ in prebuilt_objects]))
    object_files = set()
    for _, files in prebuilt_objects:
        object_files.update(files)

    return object_digest, frozenset(object_files)


# NB: We must have a description for the streaming of this rule to work properly
# (triggered by `FallibleBuiltGoPackage` subclassing `EngineAwareReturnType`).
@rule(desc="Compile with Go", level=LogLevel.DEBUG)
async def build_go_package(
    request: BuildGoPackageRequest, go_root: GoRoot
) -> FallibleBuiltGoPackage:
    maybe_built_deps = await MultiGet(
        Get(FallibleBuiltGoPackage, BuildGoPackageRequest, build_request)
        for build_request in request.direct_dependencies
    )

    import_paths_to_pkg_a_files: dict[str, str] = {}
    dep_digests = []
    for maybe_dep in maybe_built_deps:
        if maybe_dep.output is None:
            return dataclasses.replace(
                maybe_dep, import_path=request.import_path, dependency_failed=True
            )
        dep = maybe_dep.output
        for dep_import_path, pkg_archive_path in dep.import_paths_to_pkg_a_files.items():
            if dep_import_path not in import_paths_to_pkg_a_files:
                import_paths_to_pkg_a_files[dep_import_path] = pkg_archive_path
                dep_digests.append(dep.digest)

    merged_deps_digest, import_config, embedcfg, action_id_result = await MultiGet(
        Get(Digest, MergeDigests(dep_digests)),
        Get(
            ImportConfig,
            ImportConfigRequest(
                FrozenDict(import_paths_to_pkg_a_files),
                build_opts=request.build_opts,
                import_map=request.import_map,
            ),
        ),
        Get(RenderedEmbedConfig, RenderEmbedConfigRequest(request.embed_config)),
        Get(GoCompileActionIdResult, GoCompileActionIdRequest(request)),
    )

    unmerged_input_digests = [
        merged_deps_digest,
        import_config.digest,
        embedcfg.digest,
        request.digest,
    ]

    # If coverage is enabled for this package, then replace the Go source files with versions modified to
    # contain coverage code.
    go_files = request.go_files
    cgo_files = request.cgo_files
    s_files = list(request.s_files)
    go_files_digest = request.digest
    cover_file_metadatas: tuple[FileCodeCoverageMetadata, ...] | None = None
    if request.with_coverage:
        coverage_config = request.build_opts.coverage_config
        assert coverage_config is not None, "with_coverage=True but coverage_config is None!"
        coverage_result = await Get(
            ApplyCodeCoverageResult,
            ApplyCodeCoverageRequest(
                digest=request.digest,
                dir_path=request.dir_path,
                go_files=go_files,
                cgo_files=cgo_files,
                cover_mode=coverage_config.cover_mode,
                import_path=request.import_path,
            ),
        )
        go_files_digest = coverage_result.digest
        unmerged_input_digests.append(go_files_digest)
        go_files = coverage_result.go_files
        cgo_files = coverage_result.cgo_files
        cover_file_metadatas = coverage_result.cover_file_metadatas

    # Track loose object files to link into final package archive. These can come from Cgo outputs, regular
    # assembly files, or regular C files.
    objects: list[tuple[str, Digest]] = []

    # Add any prebuilt object files (".syso" extension) to the list of objects to link into the package.
    if request.prebuilt_object_files:
        objects.extend(
            (os.path.join(request.dir_path, prebuilt_object_file), request.digest)
            for prebuilt_object_file in request.prebuilt_object_files
        )

    # Process any Cgo files.
    cgo_compile_result: CGoCompileResult | None = None
    if cgo_files:
        # Check if any assembly files contain gcc assembly, and not Go assembly. Raise an exception if any are
        # likely in Go format since in cgo packages, assembly files are passed to gcc and must be in gcc format.
        #
        # Exception: When building runtime/cgo itself, only send `gcc_*.s` assembly files to GCC as
        # runtime/cgo has both types of files.
        if request.is_stdlib and request.import_path == "runtime/cgo":
            gcc_s_files = []
            new_s_files = []
            for s_file in s_files:
                if s_file.startswith("gcc_"):
                    gcc_s_files.append(s_file)
                else:
                    new_s_files.append(s_file)
            s_files = new_s_files
        else:
            asm_check_result = await Get(
                CheckForGolangAssemblyResult,
                CheckForGolangAssemblyRequest(
                    digest=request.digest,
                    dir_path=request.dir_path,
                    s_files=tuple(s_files),
                ),
            )
            if asm_check_result.maybe_golang_assembly:
                raise ValueError(
                    f"Package {request.import_path} is a cgo package but contains Go assembly files."
                )
            gcc_s_files = s_files
            s_files = []  # Clear s_files since assembly has already been handled in cgo rules.

        # Gather all prebuilt object files transitively and pass them to the Cgo rule for linking into the
        # Cgo object output. This is necessary to avoid linking errors.
        # See https://github.com/golang/go/blob/6ad27161f8d1b9c5e03fb3415977e1d3c3b11323/src/cmd/go/internal/work/exec.go#L3291-L3311.
        transitive_prebuilt_object_files = await _gather_transitive_prebuilt_object_files(request)

        assert request.cgo_flags is not None
        cgo_compile_result = await Get(
            CGoCompileResult,
            CGoCompileRequest(
                import_path=request.import_path,
                pkg_name=request.pkg_name,
                digest=go_files_digest,
                build_opts=request.build_opts,
                dir_path=request.dir_path,
                cgo_files=cgo_files,
                cgo_flags=request.cgo_flags,
                c_files=request.c_files,
                s_files=tuple(gcc_s_files),
                cxx_files=request.cxx_files,
                objc_files=request.objc_files,
                fortran_files=request.fortran_files,
                is_stdlib=request.is_stdlib,
                transitive_prebuilt_object_files=transitive_prebuilt_object_files,
            ),
        )
        assert cgo_compile_result is not None
        unmerged_input_digests.append(cgo_compile_result.digest)
        objects.extend(
            [
                (obj_file, cgo_compile_result.digest)
                for obj_file in cgo_compile_result.output_obj_files
            ]
        )

    # Copy header files with platform-specific values in their name to platform independent names.
    # For example, defs_linux_amd64.h becomes defs_GOOS_GOARCH.h.
    copied_headers_digest = await _maybe_copy_headers_to_platform_independent_names(
        input_digest=request.digest,
        dir_path=request.dir_path,
        header_files=request.header_files,
        goroot=go_root,
    )
    if copied_headers_digest:
        unmerged_input_digests.append(copied_headers_digest)

    # Merge all of the input digests together.
    input_digest = await Get(
        Digest,
        MergeDigests(unmerged_input_digests),
    )

    # If any assembly files are present, generate a "symabis" file containing API metadata about those files.
    # The "symabis" file is passed to the Go compiler when building Go code so that the compiler is aware of
    # any API exported by the assembly.
    #
    # Note: The assembly files cannot be assembled at this point because a similar process happens from Go to
    # assembly: The Go compiler generates a `go_asm.h` header file with metadata about the Go code in the package.
    symabis_path: str | None = None
    extra_assembler_flags = tuple(
        *request.build_opts.assembler_flags, *request.pkg_specific_assembler_flags
    )
    if s_files:
        symabis_fallible_result = await Get(
            FallibleGenerateAssemblySymabisResult,
            GenerateAssemblySymabisRequest(
                compilation_input=input_digest,
                s_files=tuple(s_files),
                import_path=request.import_path,
                dir_path=request.dir_path,
                extra_assembler_flags=extra_assembler_flags,
            ),
        )
        symabis_result = symabis_fallible_result.result
        if symabis_result is None:
            return FallibleBuiltGoPackage(
                None,
                request.import_path,
                symabis_fallible_result.exit_code,
                stdout=symabis_fallible_result.stdout,
                stderr=symabis_fallible_result.stderr,
            )
        input_digest = await Get(
            Digest, MergeDigests([input_digest, symabis_result.symabis_digest])
        )
        symabis_path = symabis_result.symabis_path

    # Build the arguments for compiling the Go code in this package.
    compile_args = [
        "tool",
        "compile",
        "-buildid",
        action_id_result.action_id,
        "-o",
        "__pkg__.a",
        "-pack",
        "-p",
        request.import_path,
        "-importcfg",
        import_config.CONFIG_PATH,
    ]

    # See https://github.com/golang/go/blob/f229e7031a6efb2f23241b5da000c3b3203081d6/src/cmd/go/internal/work/gc.go#L79-L100
    # for where this logic comes from.
    go_version = request.minimum_go_version or "1.16"
    if go_root.is_compatible_version(go_version):
        compile_args.extend(["-lang", f"go{go_version}"])

    if request.is_stdlib:
        compile_args.append("-std")

    compiling_runtime = request.is_stdlib and request.import_path in (
        "internal/abi",
        "internal/bytealg",
        "internal/coverage/rtcov",
        "internal/cpu",
        "internal/goarch",
        "internal/goos",
        "runtime",
        "runtime/internal/atomic",
        "runtime/internal/math",
        "runtime/internal/sys",
        "runtime/internal/syscall",
    )

    # From Go sources:
    # runtime compiles with a special gc flag to check for
    # memory allocations that are invalid in the runtime package,
    # and to implement some special compiler pragmas.
    #
    # See https://github.com/golang/go/blob/245e95dfabd77f337373bf2d6bb47cd353ad8d74/src/cmd/go/internal/work/gc.go#L107-L112
    if compiling_runtime:
        compile_args.append("-+")

    if symabis_path:
        compile_args.extend(["-symabis", symabis_path])

    # If any assembly files are present, request the compiler write an "assembly header" with API metadata
    # about the Go code that can be used by assembly files.
    asm_header_path: str | None = None
    if s_files:
        asm_header_path = str(PurePath("go_asm.h"))
        compile_args.extend(["-asmhdr", asm_header_path])

    if embedcfg.digest != EMPTY_DIGEST:
        compile_args.extend(["-embedcfg", RenderedEmbedConfig.PATH])

    if request.build_opts.with_race_detector:
        compile_args.append("-race")

    if request.build_opts.with_msan:
        compile_args.append("-msan")

    if request.build_opts.with_asan:
        compile_args.append("-asan")

    # If there are no loose object files to add to the package archive later or assembly files to assemble,
    # then pass -complete flag which tells the compiler that the provided Go files constitute the entire package.
    if not objects and not s_files:
        # Exceptions: a few standard packages have forward declarations for
        # pieces supplied behind-the-scenes by package runtime.
        if request.import_path not in (
            "bytes",
            "internal/poll",
            "net",
            "os",
            "runtime/metrics",
            "runtime/pprof",
            "runtime/trace",
            "sync",
            "syscall",
            "time",
        ):
            compile_args.append("-complete")

    # Add any extra compiler flags after the ones added automatically by this rule.
    if request.build_opts.compiler_flags:
        compile_args.extend(request.build_opts.compiler_flags)
    if request.pkg_specific_compiler_flags:
        compile_args.extend(request.pkg_specific_compiler_flags)

    # Remove -N if compiling runtime:
    #  It is not possible to build the runtime with no optimizations,
    #  because the compiler cannot eliminate enough write barriers.
    if compiling_runtime:
        compile_args = [arg for arg in compile_args if arg != "-N"]

    go_file_paths = (
        str(PurePath(request.dir_path, go_file)) if request.dir_path else f"./{go_file}"
        for go_file in go_files
    )
    generated_cgo_file_paths = cgo_compile_result.output_go_files if cgo_compile_result else ()

    # Put the source file paths into a file and pass that to `go tool compile` via a config file using the
    # `@CONFIG_FILE` syntax. This is necessary to avoid command-line argument limits on macOS. The arguments
    # may end up to exceed those limits when compiling standard library packages where we append a very long GOROOT
    # path to each file name or in packages with large numbers of files.
    go_source_file_paths_config = "\n".join([*go_file_paths, *generated_cgo_file_paths])
    go_sources_file_paths_digest = await Get(
        Digest, CreateDigest([FileContent("__sources__.txt", go_source_file_paths_config.encode())])
    )
    input_digest = await Get(Digest, MergeDigests([input_digest, go_sources_file_paths_digest]))
    compile_args.append("@__sources__.txt")

    compile_result = await Get(
        FallibleProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=tuple(compile_args),
            description=f"Compile Go package: {request.import_path}",
            output_files=("__pkg__.a", *([asm_header_path] if asm_header_path else [])),
            env={"__PANTS_GO_COMPILE_ACTION_ID": action_id_result.action_id},
        ),
    )
    if compile_result.exit_code != 0:
        return FallibleBuiltGoPackage(
            None,
            request.import_path,
            compile_result.exit_code,
            stdout=compile_result.stdout.decode("utf-8"),
            stderr=compile_result.stderr.decode("utf-8"),
        )

    compilation_digest = compile_result.output_digest

    # TODO: Compile any C files if this package does not use Cgo.

    # If any assembly files are present, then assemble them. The `compilation_digest` will contain the
    # assembly header `go_asm.h` in the object directory.
    if s_files:
        # Extract the `go_asm.h` header from the compilation output and merge into the original compilation input.
        assert asm_header_path is not None
        asm_header_digest = await Get(
            Digest,
            DigestSubset(
                compilation_digest,
                PathGlobs(
                    [asm_header_path],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin="the `build_go_package` rule",
                ),
            ),
        )
        assembly_input_digest = await Get(Digest, MergeDigests([input_digest, asm_header_digest]))
        assembly_fallible_result = await Get(
            FallibleAssembleGoAssemblyFilesResult,
            AssembleGoAssemblyFilesRequest(
                input_digest=assembly_input_digest,
                s_files=tuple(sorted(s_files)),
                dir_path=request.dir_path,
                import_path=request.import_path,
                extra_assembler_flags=extra_assembler_flags,
            ),
        )
        assembly_result = assembly_fallible_result.result
        if assembly_result is None:
            return FallibleBuiltGoPackage(
                None,
                request.import_path,
                assembly_fallible_result.exit_code,
                stdout=assembly_fallible_result.stdout,
                stderr=assembly_fallible_result.stderr,
            )
        objects.extend(assembly_result.assembly_outputs)

    # If there are any loose object files, link them into the package archive.
    if objects:
        assembly_link_input_digest = await Get(
            Digest,
            MergeDigests(
                [
                    compilation_digest,
                    *(digest for obj_file, digest in objects),
                ]
            ),
        )
        assembly_link_result = await _add_objects_to_archive(
            input_digest=assembly_link_input_digest,
            pkg_archive_path="__pkg__.a",
            obj_file_paths=sorted(obj_file for obj_file, digest in objects),
        )
        compilation_digest = assembly_link_result.output_digest

    path_prefix = os.path.join("__pkgs__", path_safe(request.import_path))
    import_paths_to_pkg_a_files[request.import_path] = os.path.join(path_prefix, "__pkg__.a")
    output_digest = await Get(Digest, AddPrefix(compilation_digest, path_prefix))
    merged_result_digest = await Get(Digest, MergeDigests([*dep_digests, output_digest]))

    # Include the modules sources in the output `Digest` alongside the package archive if the Cgo rules
    # detected a potential attempt to link against a static archive (or other reference to `${SRCDIR}` in
    # options) which necessitates the linker needing access to module sources.
    if cgo_compile_result and cgo_compile_result.include_module_sources_with_output:
        merged_result_digest = await Get(
            Digest, MergeDigests([merged_result_digest, request.digest])
        )

    coverage_metadata = (
        BuiltGoPackageCodeCoverageMetadata(
            import_path=request.import_path,
            cover_file_metadatas=cover_file_metadatas,
            sources_digest=request.digest,
            sources_dir_path=request.dir_path,
        )
        if cover_file_metadatas
        else None
    )

    output = BuiltGoPackage(
        digest=merged_result_digest,
        import_paths_to_pkg_a_files=FrozenDict(import_paths_to_pkg_a_files),
        coverage_metadata=coverage_metadata,
    )
    return FallibleBuiltGoPackage(output, request.import_path)


@rule
def required_built_go_package(fallible_result: FallibleBuiltGoPackage) -> BuiltGoPackage:
    if fallible_result.output is not None:
        return fallible_result.output
    raise Exception(
        f"Failed to compile {fallible_result.import_path}:\n"
        f"{fallible_result.stdout}\n{fallible_result.stderr}"
    )


@rule
async def render_embed_config(request: RenderEmbedConfigRequest) -> RenderedEmbedConfig:
    digest = EMPTY_DIGEST
    if request.embed_config:
        digest = await Get(
            Digest,
            CreateDigest(
                [FileContent(RenderedEmbedConfig.PATH, request.embed_config.to_embedcfg())]
            ),
        )
    return RenderedEmbedConfig(digest)


# Compute a cache key for the compile action. This computation is intended to capture similar values to the
# action ID computed by the `go` tool for its own cache.
# For details, see https://github.com/golang/go/blob/21998413ad82655fef1f31316db31e23e0684b21/src/cmd/go/internal/work/exec.go#L216-L403
@rule
async def compute_compile_action_id(
    request: GoCompileActionIdRequest, goroot: GoRoot
) -> GoCompileActionIdResult:
    bq = request.build_request

    h = hashlib.sha256()

    # All Go action IDs have the full version (as returned by `runtime.Version()`) in the key.
    # See https://github.com/golang/go/blob/master/src/cmd/go/internal/cache/hash.go#L32-L46
    h.update(goroot.full_version.encode())

    h.update(b"compile\n")
    if bq.minimum_go_version:
        h.update(f"go {bq.minimum_go_version}\n".encode())
    h.update(f"goos {goroot.goos} goarch {goroot.goarch}\n".encode())
    h.update(f"import {bq.import_path}\n".encode())
    # TODO: Consider what to do with this information from Go tool:
    # fmt.Fprintf(h, "omitdebug %v standard %v local %v prefix %q\n", p.Internal.OmitDebug, p.Standard, p.Internal.Local, p.Internal.LocalPrefix)
    # TODO: Inject cgo-related values here.
    # TODO: Inject cover mode values here.
    # TODO: Inject fuzz instrumentation values here.

    compile_tool_id = await Get(GoSdkToolIDResult, GoSdkToolIDRequest("compile"))
    h.update(f"compile {compile_tool_id.tool_id}\n".encode())
    # TODO: Add compiler flags as per `go`'s algorithm. Need to figure out
    if bq.s_files:
        asm_tool_id = await Get(GoSdkToolIDResult, GoSdkToolIDRequest("asm"))
        h.update(f"asm {asm_tool_id.tool_id}\n".encode())
        # TODO: Add asm flags as per `go`'s algorithm.
    # TODO: Add micro-architecture into cache key (e.g., GOAMD64 setting).
    if "GOEXPERIMENT" in goroot._raw_metadata:
        h.update(f"GOEXPERIMENT={goroot._raw_metadata['GOEXPERIMENT']}".encode())
    # TODO: Maybe handle go "magic" env vars: "GOCLOBBERDEADHASH", "GOSSAFUNC", "GOSSADIR", "GOSSAHASH" ?
    # TODO: Handle GSHS_LOGFILE compiler debug option by breaking cache?

    # Note: Input files are already part of cache key. Thus, this algorithm omits incorporating their
    # content hashes into the action ID.

    return GoCompileActionIdResult(h.hexdigest())


def rules():
    return (
        *collect_rules(),
        *cgo.rules(),
        *coverage.rules(),
    )
