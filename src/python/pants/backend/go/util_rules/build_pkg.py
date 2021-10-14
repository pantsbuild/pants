# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoFirstPartyPackageSourcesField,
    GoFirstPartyPackageSubpathField,
    GoImportPathField,
    GoThirdPartyModulePathField,
    GoThirdPartyModuleVersionField,
)
from pants.backend.go.util_rules.assembly import (
    AssemblyPostCompilation,
    AssemblyPostCompilationRequest,
    AssemblyPreCompilationRequest,
    FallibleAssemblyPreCompilation,
)
from pants.backend.go.util_rules.first_party_pkg import FirstPartyPkgInfo, FirstPartyPkgInfoRequest
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.backend.go.util_rules.third_party_pkg import ThirdPartyPkgInfo, ThirdPartyPkgInfoRequest
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, UnexpandedTargets, WrappedTarget
from pants.util.dirutil import fast_relpath
from pants.util.frozendict import FrozenDict
from pants.util.strutil import path_safe


@dataclass(frozen=True)
class BuildGoPackageRequest(EngineAwareParameter):
    """Build a package and its dependencies as `__pkg__.a` files."""

    import_path: str

    digest: Digest
    # Path from the root of the digest to the package to build.
    subpath: str

    go_file_names: tuple[str, ...]
    s_file_names: tuple[str, ...]

    # These dependencies themselves often have dependencies, such that we recursively build.
    direct_dependencies: tuple[BuildGoPackageRequest, ...]

    for_tests: bool = False

    def debug_hint(self) -> str | None:
        return self.import_path


@dataclass(frozen=True)
class FallibleBuiltGoPackage:
    """Fallible version of `BuiltGoPackage with error details."""

    output: BuiltGoPackage | None
    exit_code: int
    stdout: str | None = None
    stderr: str | None = None

    @classmethod
    def from_fallible_process_result(
        cls,
        process_result: FallibleProcessResult,
        output: BuiltGoPackage | None,
    ) -> FallibleBuiltGoPackage:
        return cls(
            output=output,
            exit_code=process_result.exit_code,
            stdout=process_result.stdout.decode("utf-8"),
            stderr=process_result.stderr.decode("utf-8"),
        )

    @classmethod
    def from_fallible_process_results(
        cls,
        process_results: tuple[FallibleProcessResult, ...],
        output: BuiltGoPackage | None,
    ) -> FallibleBuiltGoPackage:
        return cls(
            output=output,
            exit_code=max(process_result.exit_code for process_result in process_results),
            stdout="\n".join(
                process_result.stdout.decode("utf-8") for process_result in process_results
            ),
            stderr="\n".join(
                process_result.stderr.decode("utf-8") for process_result in process_results
            ),
        )


@dataclass(frozen=True)
class BuiltGoPackage:
    """A package and its dependencies compiled as `__pkg__.a` files.

    The packages are arranged into `__pkgs__/{path_safe(import_path)}/__pkg__.a`.
    """

    digest: Digest
    import_paths_to_pkg_a_files: FrozenDict[str, str]


@rule
async def build_go_package(request: BuildGoPackageRequest) -> FallibleBuiltGoPackage:
    built_deps = await MultiGet(
        Get(BuiltGoPackage, BuildGoPackageRequest, build_request)
        for build_request in request.direct_dependencies
    )

    import_paths_to_pkg_a_files: dict[str, str] = {}
    dep_digests = []
    for dep in built_deps:
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
        if assembly_setup.has_failures():
            return FallibleBuiltGoPackage.from_fallible_process_results(
                assembly_setup.results, None
            )
        assert assembly_setup.output
        input_digest = assembly_setup.output.merged_compilation_input_digest
        assembly_digests = assembly_setup.output.assembly_digests
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
        return FallibleBuiltGoPackage.from_fallible_process_result(compile_result, None)

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
            return FallibleBuiltGoPackage.from_fallible_process_result(assembly_result.result, None)
        assert assembly_result.merged_output_digest
        compilation_digest = assembly_result.merged_output_digest

    path_prefix = os.path.join("__pkgs__", path_safe(request.import_path))
    import_paths_to_pkg_a_files[request.import_path] = os.path.join(path_prefix, "__pkg__.a")
    output_digest = await Get(Digest, AddPrefix(compilation_digest, path_prefix))
    merged_result_digest = await Get(Digest, MergeDigests([*dep_digests, output_digest]))

    output = BuiltGoPackage(merged_result_digest, FrozenDict(import_paths_to_pkg_a_files))
    return FallibleBuiltGoPackage.from_fallible_process_result(compile_result, output)


@rule
def required_built_go_package(fallible_result: FallibleBuiltGoPackage) -> BuiltGoPackage:
    if fallible_result.exit_code == 0:
        assert fallible_result.output
        return fallible_result.output
    # TODO(12927): Wire up to streaming workunit system to log compilation results.
    raise Exception(
        f"Compile failed:\nstdout:\n{fallible_result.stdout}\nstderr:\n{fallible_result.stderr}"
    )


@dataclass(frozen=True)
class BuildGoPackageTargetRequest(EngineAwareParameter):
    """Build a `go_first_party_package` or `go_third_party_package` target and its dependencies as
    `__pkg__.a` files."""

    address: Address
    is_main: bool = False
    for_tests: bool = False

    def debug_hint(self) -> str:
        return str(self.address)


@rule
async def setup_build_go_package_target_request(
    request: BuildGoPackageTargetRequest,
) -> BuildGoPackageRequest:
    wrapped_target = await Get(WrappedTarget, Address, request.address)
    target = wrapped_target.target
    import_path = target[GoImportPathField].value

    if target.has_field(GoFirstPartyPackageSourcesField):
        _first_party_pkg_info = await Get(
            FirstPartyPkgInfo, FirstPartyPkgInfoRequest(target.address)
        )
        digest = _first_party_pkg_info.digest
        subpath = os.path.join(
            target.address.spec_path, target[GoFirstPartyPackageSubpathField].value
        )
        go_file_names = _first_party_pkg_info.go_files
        if request.for_tests:
            # TODO: Build the test sources separately and link the two object files into the package archive?
            # TODO: The `go` tool changes the displayed import path for the package when it has test files. Do we
            #   need to do something similar?
            go_file_names += _first_party_pkg_info.test_files
        s_file_names = _first_party_pkg_info.s_files

    elif target.has_field(GoThirdPartyModulePathField):
        _module_path = target[GoThirdPartyModulePathField].value
        subpath = fast_relpath(import_path, _module_path)

        _go_mod_address = target.address.maybe_convert_to_target_generator()
        _go_mod_info = await Get(GoModInfo, GoModInfoRequest(_go_mod_address))
        _third_party_pkg_info = await Get(
            ThirdPartyPkgInfo,
            ThirdPartyPkgInfoRequest(
                import_path=import_path,
                module_path=_module_path,
                version=target[GoThirdPartyModuleVersionField].value,
                go_mod_stripped_digest=_go_mod_info.stripped_digest,
            ),
        )

        digest = _third_party_pkg_info.digest
        go_file_names = _third_party_pkg_info.go_files
        s_file_names = _third_party_pkg_info.s_files

    else:
        raise AssertionError(
            f"Unknown how to build `{target.alias}` target at address {request.address} with Go."
            "Please open a bug at https://github.com/pantsbuild/pants/issues/new/choose with this "
            "message!"
        )

    # TODO: If you use `Targets` here, then we replace the direct dep on the `go_mod` with all
    #  of its generated targets...Figure this out.
    all_deps = await Get(UnexpandedTargets, DependenciesRequest(target[Dependencies]))
    direct_dependencies = await MultiGet(
        Get(BuildGoPackageRequest, BuildGoPackageTargetRequest(tgt.address))
        for tgt in all_deps
        if (
            tgt.has_field(GoFirstPartyPackageSourcesField)
            or tgt.has_field(GoThirdPartyModulePathField)
        )
    )

    return BuildGoPackageRequest(
        digest=digest,
        import_path="main" if request.is_main else import_path,
        subpath=subpath,
        go_file_names=go_file_names,
        s_file_names=s_file_names,
        direct_dependencies=direct_dependencies,
        for_tests=request.for_tests,
    )


def rules():
    return collect_rules()
