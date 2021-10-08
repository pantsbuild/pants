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
    AssemblyPreCompilation,
    AssemblyPreCompilationRequest,
)
from pants.backend.go.util_rules.compile import CompiledGoSources, CompileGoSourcesRequest
from pants.backend.go.util_rules.first_party_pkg import FirstPartyPkgInfo, FirstPartyPkgInfoRequest
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.third_party_pkg import ThirdPartyPkgInfo, ThirdPartyPkgInfoRequest
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, UnexpandedTargets, WrappedTarget
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

    def debug_hint(self) -> str | None:
        return self.import_path


@dataclass(frozen=True)
class BuiltGoPackage:
    """A package and its dependencies compiled as `__pkg__.a` files.

    The packages are arranged into `__pkgs__/{path_safe(import_path)}/__pkg__.a`.
    """

    digest: Digest
    import_paths_to_pkg_a_files: FrozenDict[str, str]


@rule
async def build_go_package(request: BuildGoPackageRequest) -> BuiltGoPackage:
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
            AssemblyPreCompilation,
            AssemblyPreCompilationRequest(input_digest, request.s_file_names, request.subpath),
        )
        input_digest = assembly_setup.merged_compilation_input_digest
        assembly_digests = assembly_setup.assembly_digests
        symabis_path = "./symabis"

    result = await Get(
        CompiledGoSources,
        CompileGoSourcesRequest(
            digest=input_digest,
            sources=tuple(
                f"./{request.subpath}/{name}" if request.subpath else f"./{name}"
                for name in request.go_file_names
            ),
            import_path=request.import_path,
            description=f"Compile Go package: {request.import_path}",
            import_config_path=import_config.CONFIG_PATH,
            symabis_path=symabis_path,
        ),
    )
    compilation_digest = result.output_digest
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
        compilation_digest = assembly_result.merged_output_digest

    path_prefix = os.path.join("__pkgs__", path_safe(request.import_path))
    import_paths_to_pkg_a_files[request.import_path] = os.path.join(path_prefix, "__pkg__.a")
    output_digest = await Get(Digest, AddPrefix(compilation_digest, path_prefix))
    merged_result_digest = await Get(Digest, MergeDigests([*dep_digests, output_digest]))

    return BuiltGoPackage(merged_result_digest, FrozenDict(import_paths_to_pkg_a_files))


@dataclass(frozen=True)
class BuildGoPackageTargetRequest(EngineAwareParameter):
    """Build a `go_first_party_package` or `go_third_party_package` target and its dependencies as
    `__pkg__.a` files."""

    address: Address
    is_main: bool = False

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
        s_file_names = _first_party_pkg_info.s_files

    elif target.has_field(GoThirdPartyModulePathField):
        _module_path = target[GoThirdPartyModulePathField].value
        subpath = import_path[len(_module_path) :]

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
    )


def rules():
    return collect_rules()
