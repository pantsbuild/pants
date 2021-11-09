# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import os.path
from dataclasses import dataclass

from pants.backend.go.util_rules.assembly import (
    AssemblyPostCompilation,
    AssemblyPostCompilationRequest,
    AssemblyPreCompilationRequest,
    FallibleAssemblyPreCompilation,
)
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import path_safe


class BuildGoPackageRequest(EngineAwareParameter):
    def __init__(
        self,
        *,
        import_path: str,
        digest: Digest,
        subpath: str,
        go_file_names: tuple[str, ...],
        s_file_names: tuple[str, ...],
        direct_dependencies: tuple[BuildGoPackageRequest, ...],
        for_tests: bool = False,
    ) -> None:
        """Build a package and its dependencies as `__pkg__.a` files.

        Instances of this class form a structure-shared DAG, and so a hashcode is pre-computed for
        the recursive portion.
        """

        self.import_path = import_path
        self.digest = digest
        self.subpath = subpath
        self.go_file_names = go_file_names
        self.s_file_names = s_file_names
        self.direct_dependencies = direct_dependencies
        self.for_tests = for_tests
        self._hashcode = hash(
            (
                self.import_path,
                self.digest,
                self.subpath,
                self.go_file_names,
                self.s_file_names,
                self.direct_dependencies,
                self.for_tests,
            )
        )

    def __repr__(self) -> str:
        # NB: We must override the default `__repr__` so that `direct_dependencies` does not
        # traverse into transitive dependencies, which was pathologically slow.
        return (
            f"{self.__class__}("
            f"import_path={repr(self.import_path)}, "
            f"digest={self.digest}, "
            f"subpath={self.subpath}, "
            f"go_file_names={self.go_file_names}, "
            f"go_file_names={self.s_file_names}, "
            f"direct_dependencies={[dep.import_path for dep in self.direct_dependencies]}, "
            f"for_tests={self.for_tests}"
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
            and self.digest == other.digest
            and self.subpath == other.subpath
            and self.go_file_names == other.go_file_names
            and self.s_file_names == other.s_file_names
            and self.for_tests == other.for_tests
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


# NB: We must have a description for the streaming of this rule to work properly
# (triggered by `FallibleBuiltGoPackage` subclassing `EngineAwareReturnType`).
@rule(desc="Compile with Go", level=LogLevel.DEBUG)
async def build_go_package(request: BuildGoPackageRequest) -> FallibleBuiltGoPackage:
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

    merged_deps_digest, import_config = await MultiGet(
        Get(Digest, MergeDigests(dep_digests)),
        Get(ImportConfig, ImportConfigRequest(FrozenDict(import_paths_to_pkg_a_files))),
    )

    input_digest = await Get(
        Digest, MergeDigests([merged_deps_digest, import_config.digest, request.digest])
    )

    assembly_digests = None
    symabis_path = None
    if request.s_file_names:
        assembly_setup = await Get(
            FallibleAssemblyPreCompilation,
            AssemblyPreCompilationRequest(input_digest, request.s_file_names, request.subpath),
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
        "-o",
        "__pkg__.a",
        "-pack",
        "-p",
        request.import_path,
        "-importcfg",
        import_config.CONFIG_PATH,
    ]
    if symabis_path:
        compile_args.extend(["-symabis", symabis_path])
    relativized_sources = (
        f"./{request.subpath}/{name}" if request.subpath else f"./{name}"
        for name in request.go_file_names
    )
    compile_args.extend(["--", *relativized_sources])
    compile_result = await Get(
        FallibleProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=tuple(compile_args),
            description=f"Compile Go package: {request.import_path}",
            output_files=("__pkg__.a",),
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
                compilation_digest,
                assembly_digests,
                request.s_file_names,
                request.subpath,
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

    path_prefix = os.path.join("__pkgs__", path_safe(request.import_path))
    import_paths_to_pkg_a_files[request.import_path] = os.path.join(path_prefix, "__pkg__.a")
    output_digest = await Get(Digest, AddPrefix(compilation_digest, path_prefix))
    merged_result_digest = await Get(Digest, MergeDigests([*dep_digests, output_digest]))

    output = BuiltGoPackage(merged_result_digest, FrozenDict(import_paths_to_pkg_a_files))
    return FallibleBuiltGoPackage(output, request.import_path)


@rule
def required_built_go_package(fallible_result: FallibleBuiltGoPackage) -> BuiltGoPackage:
    if fallible_result.output is not None:
        return fallible_result.output
    raise Exception(
        f"Failed to compile {fallible_result.import_path}:\n"
        f"{fallible_result.stdout}\n{fallible_result.stderr}"
    )


def rules():
    return collect_rules()
