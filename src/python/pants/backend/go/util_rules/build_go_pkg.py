# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from dataclasses import dataclass
from typing import Optional

from pants.backend.go.target_types import (
    GoExternalModulePathField,
    GoExternalModuleVersionField,
    GoExternalPackageTarget,
    GoPackageSources,
)
from pants.backend.go.util_rules.assembly import (
    AssemblyPostCompilation,
    AssemblyPostCompilationRequest,
    AssemblyPreCompilation,
    AssemblyPreCompilationRequest,
)
from pants.backend.go.util_rules.compile import CompiledGoSources, CompileGoSourcesRequest
from pants.backend.go.util_rules.external_module import (
    DownloadedExternalModules,
    DownloadExternalModulesRequest,
    ResolveExternalGoPackageRequest,
)
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.backend.go.util_rules.go_pkg import (
    ResolvedGoPackage,
    ResolveGoPackageRequest,
    is_first_party_package_target,
    is_third_party_package_target,
)
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import AddPrefix, Digest, DigestSubset, MergeDigests, PathGlobs, RemovePrefix
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, UnexpandedTargets, WrappedTarget
from pants.util.frozendict import FrozenDict
from pants.util.strutil import path_safe


@dataclass(frozen=True)
class BuildGoPackageRequest(EngineAwareParameter):
    """Build a package and its dependencies as `__pkg__.a` files."""

    address: Address
    is_main: bool = False

    def debug_hint(self) -> Optional[str]:
        return str(self.address)


@dataclass(frozen=True)
class BuiltGoPackage:
    """A package and its dependencies compiled as `__pkg__.a` files.

    The packages are arranged into `__pkgs__/{path_safe(import_path)}/__pkg__.a`.
    """

    digest: Digest
    import_paths_to_pkg_a_files: FrozenDict[str, str]


@rule
async def build_go_package(request: BuildGoPackageRequest) -> BuiltGoPackage:
    wrapped_target = await Get(WrappedTarget, Address, request.address)
    target = wrapped_target.target

    if is_first_party_package_target(target):
        source_files, resolved_package = await MultiGet(
            Get(
                SourceFiles,
                SourceFilesRequest((target[GoPackageSources],)),
            ),
            Get(ResolvedGoPackage, ResolveGoPackageRequest(address=target.address)),
        )
        source_files_digest = source_files.snapshot.digest
        source_files_subpath = target.address.spec_path
    elif is_third_party_package_target(target):
        assert isinstance(target, GoExternalPackageTarget)
        owning_go_mod = await Get(OwningGoMod, OwningGoModRequest(target.address))
        go_mod_info = await Get(GoModInfo, GoModInfoRequest(owning_go_mod.address))
        module_path = target[GoExternalModulePathField].value
        _downloaded_modules, resolved_package = await MultiGet(
            Get(
                DownloadedExternalModules,
                DownloadExternalModulesRequest(go_mod_info.stripped_digest),
            ),
            Get(
                ResolvedGoPackage,
                ResolveExternalGoPackageRequest(target, go_mod_info.stripped_digest),
            ),
        )
        # TODO: generalize this code.
        _module_dir = _downloaded_modules.module_dir(
            module_path, target[GoExternalModuleVersionField].value
        )
        _downloaded_module = await Get(
            Digest, DigestSubset(_downloaded_modules.digest, PathGlobs([f"{_module_dir}/**"]))
        )
        source_files_digest = await Get(Digest, RemovePrefix(_downloaded_module, _module_dir))
        source_files_subpath = resolved_package.import_path[len(module_path) :]
    else:
        raise AssertionError(f"Unknown how to build target at address {request.address} with Go.")

    import_path = "main" if request.is_main else resolved_package.import_path

    # TODO: If you use `Targets` here, then we replace the direct dep on the `go_mod` with all
    #  of its generated targets...Figure this out.
    _all_dependencies = await Get(UnexpandedTargets, DependenciesRequest(target[Dependencies]))
    _buildable_dependencies = [
        dep
        for dep in _all_dependencies
        if is_first_party_package_target(dep) or is_third_party_package_target(dep)
    ]
    built_deps = await MultiGet(
        Get(BuiltGoPackage, BuildGoPackageRequest(tgt.address)) for tgt in _buildable_dependencies
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
        Digest, MergeDigests([merged_deps_digest, import_config.digest, source_files_digest])
    )

    assembly_digests = None
    symabis_path = None
    if resolved_package.s_files:
        assembly_setup = await Get(
            AssemblyPreCompilation,
            AssemblyPreCompilationRequest(
                input_digest, resolved_package.s_files, source_files_subpath
            ),
        )
        input_digest = assembly_setup.merged_compilation_input_digest
        assembly_digests = assembly_setup.assembly_digests
        symabis_path = "./symabis"

    result = await Get(
        CompiledGoSources,
        CompileGoSourcesRequest(
            digest=input_digest,
            sources=tuple(f"./{source_files_subpath}/{name}" for name in resolved_package.go_files),
            import_path=import_path,
            description=f"Compile Go package: {import_path}",
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
                resolved_package.s_files,
                source_files_subpath,
            ),
        )
        compilation_digest = assembly_result.merged_output_digest

    _path_prefix = os.path.join("__pkgs__", path_safe(import_path))
    import_paths_to_pkg_a_files[import_path] = os.path.join(_path_prefix, "__pkg__.a")
    _output_digest = await Get(Digest, AddPrefix(compilation_digest, _path_prefix))
    merged_result_digest = await Get(Digest, MergeDigests([*dep_digests, _output_digest]))

    return BuiltGoPackage(merged_result_digest, FrozenDict(import_paths_to_pkg_a_files))


def rules():
    return collect_rules()
