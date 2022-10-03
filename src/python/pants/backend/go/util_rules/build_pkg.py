# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import hashlib
import os.path
from dataclasses import dataclass
from typing import Iterable

from pants.backend.go.util_rules import cgo, coverage
from pants.backend.go.util_rules.assembly import (
    AssemblyPostCompilation,
    AssemblyPostCompilationRequest,
    AssemblyPreCompilationRequest,
    FallibleAssemblyPreCompilation,
)
from pants.backend.go.util_rules.cgo import CGoCompileRequest, CGoCompileResult, CGoCompilerFlags
from pants.backend.go.util_rules.coverage import (
    ApplyCodeCoverageRequest,
    ApplyCodeCoverageResult,
    BuiltGoPackageCodeCoverageMetadata,
    FileCodeCoverageMetadata,
    GoCoverageConfig,
)
from pants.backend.go.util_rules.embedcfg import EmbedConfig
from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, GoSdkToolIDResult
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    MergeDigests,
    PathGlobs,
)
from pants.engine.process import FallibleProcessResult, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule, rule_helper
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import path_safe


class BuildGoPackageRequest(EngineAwareParameter):
    def __init__(
        self,
        *,
        import_path: str,
        pkg_name: str,
        digest: Digest,
        dir_path: str,
        go_files: tuple[str, ...],
        s_files: tuple[str, ...],
        direct_dependencies: tuple[BuildGoPackageRequest, ...],
        minimum_go_version: str | None,
        for_tests: bool = False,
        embed_config: EmbedConfig | None = None,
        coverage_config: GoCoverageConfig | None = None,
        cgo_files: tuple[str, ...] = (),
        cgo_flags: CGoCompilerFlags | None = None,
        c_files: tuple[str, ...] = (),
        cxx_files: tuple[str, ...] = (),
        objc_files: tuple[str, ...] = (),
        fortran_files: tuple[str, ...] = (),
    ) -> None:
        """Build a package and its dependencies as `__pkg__.a` files.

        Instances of this class form a structure-shared DAG, and so a hashcode is pre-computed for
        the recursive portion.
        """

        self.import_path = import_path
        self.pkg_name = pkg_name
        self.digest = digest
        self.dir_path = dir_path
        self.go_files = go_files
        self.s_files = s_files
        self.direct_dependencies = direct_dependencies
        self.minimum_go_version = minimum_go_version
        self.for_tests = for_tests
        self.embed_config = embed_config
        self.coverage_config = coverage_config
        self.cgo_files = cgo_files
        self.cgo_flags = cgo_flags
        self.c_files = c_files
        self.cxx_files = cxx_files
        self.objc_files = objc_files
        self.fortran_files = fortran_files
        self._hashcode = hash(
            (
                self.import_path,
                self.pkg_name,
                self.digest,
                self.dir_path,
                self.go_files,
                self.s_files,
                self.direct_dependencies,
                self.minimum_go_version,
                self.for_tests,
                self.embed_config,
                self.coverage_config,
                self.cgo_files,
                self.cgo_flags,
                self.c_files,
                self.cxx_files,
                self.objc_files,
                self.fortran_files,
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
            f"go_files={self.go_files}, "
            f"s_files={self.s_files}, "
            f"direct_dependencies={[dep.import_path for dep in self.direct_dependencies]}, "
            f"minimum_go_version={self.minimum_go_version}, "
            f"for_tests={self.for_tests}, "
            f"embed_config={self.embed_config}, "
            f"coverage_config={self.coverage_config}, "
            f"cgo_files={self.cgo_files}, "
            f"cgo_flags={self.cgo_flags}, "
            f"c_files={self.c_files}, "
            f"cxx_files={self.cxx_files}, "
            f"objc_files={self.objc_files}, "
            f"fortran_files={self.fortran_files}"
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
            and self.go_files == other.go_files
            and self.s_files == other.s_files
            and self.minimum_go_version == other.minimum_go_version
            and self.for_tests == other.for_tests
            and self.embed_config == other.embed_config
            and self.coverage_config == other.coverage_config
            and self.cgo_files == other.cgo_files
            and self.cgo_flags == other.cgo_flags
            and self.c_files == other.c_files
            and self.cxx_files == other.cxx_files
            and self.objc_files == other.objc_files
            and self.fortran_files == other.fortran_files
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
@rule_helper
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


def _maybe_is_golang_assembly(data: bytes) -> bool:
    """Return true if `data` looks like it could be a Golang-format assembly language file.

    This is used by the cgo rules as a heuristic to determine if the user is passing Golang assembly
    format instead of gcc assembly format.
    """
    return (
        data.startswith(b"TEXT")
        or b"\nTEXT" in data
        or data.startswith(b"DATA")
        or b"\nDATA" in data
        or data.startswith(b"GLOBL")
        or b"\nGLOBL" in data
    )


@rule_helper
async def _any_file_is_golang_assembly(
    digest: Digest, dir_path: str, s_files: Iterable[str]
) -> bool:
    """Return true if any of the given `s_files` look like it could be a Golang-format assembly
    language file.

    This is used by the cgo rules as a heuristic to determine if the user is passing Golang assembly
    format instead of gcc assembly format.
    """
    digest_contents = await Get(
        DigestContents,
        DigestSubset(
            digest,
            PathGlobs(
                globs=[os.path.join(dir_path, s_file) for s_file in s_files],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin="golang cgo rules",
            ),
        ),
    )
    for s_file in s_files:
        for entry in digest_contents:
            if entry.path == os.path.join(dir_path, s_file):
                if _maybe_is_golang_assembly(entry.content):
                    return True
    return False


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
        import_paths_to_pkg_a_files.update(dep.import_paths_to_pkg_a_files)
        dep_digests.append(dep.digest)

    merged_deps_digest, import_config, embedcfg, action_id_result = await MultiGet(
        Get(Digest, MergeDigests(dep_digests)),
        Get(ImportConfig, ImportConfigRequest(FrozenDict(import_paths_to_pkg_a_files))),
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
    if request.coverage_config:
        coverage_result = await Get(
            ApplyCodeCoverageResult,
            ApplyCodeCoverageRequest(
                digest=request.digest,
                dir_path=request.dir_path,
                go_files=go_files,
                cgo_files=cgo_files,
                cover_mode=request.coverage_config.cover_mode,
                import_path=request.import_path,
            ),
        )
        go_files_digest = coverage_result.digest
        unmerged_input_digests.append(go_files_digest)
        go_files = coverage_result.go_files
        cgo_files = coverage_result.cgo_files
        cover_file_metadatas = coverage_result.cover_file_metadatas

    cgo_compile_result: CGoCompileResult | None = None
    if cgo_files:
        # Check if any assembly files contain gcc assembly, and not Go assembly. Raise an exception if any are
        # likely in Go format since in cgo packages, assembly files are passed to gcc and must be in gcc format.
        if s_files and await _any_file_is_golang_assembly(
            request.digest, request.dir_path, s_files
        ):
            raise ValueError(
                f"Package {request.import_path} is a cgo package but contains Go assembly files."
            )

        assert request.cgo_flags is not None
        cgo_compile_result = await Get(
            CGoCompileResult,
            CGoCompileRequest(
                import_path=request.import_path,
                pkg_name=request.pkg_name,
                digest=go_files_digest,
                dir_path=request.dir_path,
                cgo_files=cgo_files,
                cgo_flags=request.cgo_flags,
                c_files=request.c_files,
                s_files=tuple(s_files),
                cxx_files=request.cxx_files,
                objc_files=request.objc_files,
                fortran_files=request.fortran_files,
            ),
        )
        assert cgo_compile_result is not None
        unmerged_input_digests.append(cgo_compile_result.digest)
        s_files = []  # Clear s_files since assembly has already been handled in cgo rules.

    input_digest = await Get(
        Digest,
        MergeDigests(unmerged_input_digests),
    )

    assembly_digests = None
    symabis_path = None
    if s_files:
        assembly_setup = await Get(
            FallibleAssemblyPreCompilation,
            AssemblyPreCompilationRequest(
                compilation_input=input_digest,
                s_files=tuple(s_files),
                dir_path=request.dir_path,
                import_path=request.import_path,
            ),
        )
        if assembly_setup.result is None:
            return FallibleBuiltGoPackage(
                None,
                request.import_path,
                assembly_setup.exit_code,
                stdout=assembly_setup.stdout,
                stderr=assembly_setup.stderr,
            )
        input_digest = assembly_setup.result.merged_compilation_input_digest
        assembly_digests = assembly_setup.result.assembly_digests
        symabis_path = "./symabis"

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
        compile_args.append(f"-lang=go{go_version}")

    if symabis_path:
        compile_args.extend(["-symabis", symabis_path])

    if embedcfg.digest != EMPTY_DIGEST:
        compile_args.extend(["-embedcfg", RenderedEmbedConfig.PATH])

    if not s_files:
        # If there are no non-Go sources, then pass -complete flag which tells the compiler that the provided
        # Go files are the entire package.
        compile_args.append("-complete")

    relativized_sources = (
        f"./{request.dir_path}/{name}" if request.dir_path else f"./{name}" for name in go_files
    )
    generated_cgo_file_paths = cgo_compile_result.output_go_files if cgo_compile_result else ()
    compile_args.extend(["--", *relativized_sources, *generated_cgo_file_paths])
    compile_result = await Get(
        FallibleProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=tuple(compile_args),
            description=f"Compile Go package: {request.import_path}",
            output_files=("__pkg__.a",),
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
    if assembly_digests:
        assembly_result = await Get(
            AssemblyPostCompilation,
            AssemblyPostCompilationRequest(
                compilation_result=compilation_digest,
                assembly_digests=assembly_digests,
                s_files=tuple(s_files),
                dir_path=request.dir_path,
            ),
        )
        if assembly_result.result.exit_code != 0:
            return FallibleBuiltGoPackage(
                None,
                request.import_path,
                assembly_result.result.exit_code,
                stdout=assembly_result.result.stdout.decode("utf-8"),
                stderr=assembly_result.result.stderr.decode("utf-8"),
            )
        assert assembly_result.merged_output_digest
        compilation_digest = assembly_result.merged_output_digest

    if cgo_compile_result:
        cgo_link_input_digest = await Get(
            Digest,
            MergeDigests(
                [
                    compilation_digest,
                    cgo_compile_result.digest,
                ]
            ),
        )
        cgo_link_result = await _add_objects_to_archive(
            input_digest=cgo_link_input_digest,
            pkg_archive_path="__pkg__.a",
            obj_file_paths=cgo_compile_result.output_obj_files,
        )
        compilation_digest = cgo_link_result.output_digest

    path_prefix = os.path.join("__pkgs__", path_safe(request.import_path))
    import_paths_to_pkg_a_files[request.import_path] = os.path.join(path_prefix, "__pkg__.a")
    output_digest = await Get(Digest, AddPrefix(compilation_digest, path_prefix))
    merged_result_digest = await Get(Digest, MergeDigests([*dep_digests, output_digest]))

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

    # All Go action IDs have the full version (as returned by `runtime.Version()` in the key.
    # See https://github.com/golang/go/blob/master/src/cmd/go/internal/cache/hash.go#L32-L46
    h.update(goroot.full_version.encode())

    h.update("compile\n".encode())
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
