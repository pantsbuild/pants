# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

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
    DownloadedExternalModule,
    DownloadExternalModuleRequest,
    ResolveExternalGoPackageRequest,
)
from pants.backend.go.util_rules.go_pkg import (
    ResolvedGoPackage,
    ResolveGoPackageRequest,
    is_first_party_package_target,
    is_third_party_package_target,
)
from pants.backend.go.util_rules.import_analysis import GatheredImports, GatherImportsRequest
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest, MergeDigests
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Dependencies, DependenciesRequest, UnexpandedTargets, WrappedTarget
from pants.util.ordered_set import FrozenOrderedSet
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class BuildGoPackageRequest(EngineAwareParameter):
    address: Address
    is_main: bool = False

    def debug_hint(self) -> Optional[str]:
        return str(self.address)


@dataclass(frozen=True)
class BuiltGoPackage:
    import_path: str
    object_digest: Digest
    imports_digest: Digest


@rule
async def build_target(
    request: BuildGoPackageRequest,
) -> BuiltGoPackage:
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
        module_path = target[GoExternalModulePathField].value
        module, resolved_package = await MultiGet(
            Get(
                DownloadedExternalModule,
                DownloadExternalModuleRequest(
                    path=module_path,
                    version=target[GoExternalModuleVersionField].value,
                ),
            ),
            Get(ResolvedGoPackage, ResolveExternalGoPackageRequest(target)),
        )

        source_files_digest = module.digest
        source_files_subpath = resolved_package.import_path[len(module_path) :]
    else:
        raise ValueError(f"Unknown how to build Go target at address {request.address}.")

    dependencies = await Get(Addresses, DependenciesRequest(field=target[Dependencies]))
    dependencies_targets = await Get(UnexpandedTargets, Addresses(dependencies))
    buildable_dependencies_targets = [
        dep_tgt
        for dep_tgt in dependencies_targets
        if is_first_party_package_target(dep_tgt) or is_third_party_package_target(dep_tgt)
    ]
    built_go_deps = await MultiGet(
        Get(BuiltGoPackage, BuildGoPackageRequest(tgt.address))
        for tgt in buildable_dependencies_targets
    )

    gathered_imports = await Get(
        GatheredImports,
        GatherImportsRequest(packages=FrozenOrderedSet(built_go_deps), include_stdlib=True),
    )

    import_path = resolved_package.import_path
    if request.is_main:
        import_path = "main"

    input_digest = await Get(Digest, MergeDigests([gathered_imports.digest, source_files_digest]))

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
            description=f"Compile Go package with {pluralize(len(resolved_package.go_files), 'file')}.",
            import_config_path="./importcfg",
            symabis_path=symabis_path,
        ),
    )
    output_digest = result.output_digest

    if assembly_digests:
        assembly_result = await Get(
            AssemblyPostCompilation,
            AssemblyPostCompilationRequest(
                output_digest, assembly_digests, resolved_package.s_files, source_files_subpath
            ),
        )
        output_digest = assembly_result.merged_output_digest

    return BuiltGoPackage(
        import_path=import_path,
        object_digest=output_digest,
        imports_digest=gathered_imports.digest,
    )


def rules():
    return collect_rules()
