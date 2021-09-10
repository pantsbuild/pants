# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import List, Optional

from pants.backend.go.import_analysis import ResolvedImportPathsForGoLangDistribution
from pants.backend.go.module import DownloadedExternalModule, DownloadExternalModuleRequest
from pants.backend.go.pkg import (
    ResolvedGoPackage,
    ResolveExternalGoPackageRequest,
    ResolveGoPackageRequest,
    is_first_party_package_target,
    is_third_party_package_target,
)
from pants.backend.go.sdk import GoSdkProcess
from pants.backend.go.target_types import (
    GoBinaryMainAddress,
    GoExternalModulePath,
    GoExternalModuleVersion,
    GoImportPath,
    GoPackageSources,
    GoSources,
)
from pants.build_graph.address import Address, AddressInput
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import AddPrefix, CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSet,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


class GoBuildSubsystem(GoalSubsystem):
    name = "go-build"
    help = "Compile Go targets that contain source code (i.e., `go_package`)."


class GoBuildGoal(Goal):
    subsystem_cls = GoBuildSubsystem


@dataclass(frozen=True)
class BuildGoPackageFieldSet(FieldSet):
    required_fields = (GoImportPath,)
    sources: GoSources
    module_path: GoExternalModulePath
    module_version: GoExternalModuleVersion
    import_path: GoImportPath


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


@dataclass(frozen=True)
class GoBinaryFieldSet(PackageFieldSet):
    required_fields = (GoBinaryMainAddress,)

    main_address: GoBinaryMainAddress
    output_path: OutputPathField


@goal_rule
async def run_go_build(targets: UnexpandedTargets) -> GoBuildGoal:
    await MultiGet(
        Get(BuiltGoPackage, BuildGoPackageRequest(address=tgt.address))
        for tgt in targets
        if is_first_party_package_target(tgt) or is_third_party_package_target(tgt)
    )
    return GoBuildGoal(exit_code=0)


@dataclass(frozen=True)
class GatherImportsRequest:
    packages: FrozenOrderedSet[BuiltGoPackage]
    include_stdlib: bool


@dataclass(frozen=True)
class GatheredImports:
    digest: Digest


@rule
async def generate_import_config(
    request: GatherImportsRequest, goroot_import_mappings: ResolvedImportPathsForGoLangDistribution
) -> GatheredImports:
    import_config_digests: dict[str, tuple[str, Digest]] = {}
    for pkg in request.packages:
        fp = pkg.object_digest.fingerprint
        prefixed_digest = await Get(Digest, AddPrefix(pkg.object_digest, f"__pkgs__/{fp}"))
        import_config_digests[pkg.import_path] = (fp, prefixed_digest)

    pkg_digests: OrderedSet[Digest] = OrderedSet()

    import_config: List[str] = ["# import config"]
    for import_path, (fp, digest) in import_config_digests.items():
        pkg_digests.add(digest)
        import_config.append(f"packagefile {import_path}=__pkgs__/{fp}/__pkg__.a")

    if request.include_stdlib:
        for stdlib_pkg_importpath, stdlib_pkg in goroot_import_mappings.import_path_mapping.items():
            pkg_digests.add(stdlib_pkg.digest)
            import_config.append(
                f"packagefile {stdlib_pkg_importpath}={os.path.normpath(stdlib_pkg.path)}"
            )

    import_config_content = "\n".join(import_config).encode("utf-8")

    import_config_digest = await Get(
        Digest, CreateDigest([FileContent(path="./importcfg", content=import_config_content)])
    )
    pkg_digests.add(import_config_digest)

    digest = await Get(Digest, MergeDigests(pkg_digests))

    return GatheredImports(digest=digest)


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
        module_path = target[GoExternalModulePath].value
        if not module_path:
            raise ValueError(f"_go_ext_mod_package at address {request.address} has a blank `path`")

        module_version = target[GoExternalModuleVersion].value
        if not module_version:
            raise ValueError(
                f"_go_ext_mod_package at address {request.address} has a blank `version`"
            )

        module, resolved_package = await MultiGet(
            Get(
                DownloadedExternalModule,
                DownloadExternalModuleRequest(
                    path=module_path,
                    version=module_version,
                ),
            ),
            Get(ResolvedGoPackage, ResolveExternalGoPackageRequest(address=request.address)),
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
        GatherImportsRequest(
            packages=FrozenOrderedSet(built_go_deps),
            include_stdlib=True,
        ),
    )

    input_digest = await Get(
        Digest,
        MergeDigests([gathered_imports.digest, source_files_digest]),
    )

    import_path = resolved_package.import_path
    if request.is_main:
        import_path = "main"

    # If there are any .s assembly files to be built, then generate a "symabis" file for consumption by Go compiler.
    # See https://github.com/bazelbuild/rules_go/issues/1893 (rules_go)
    # TODO(12762): Refactor to separate rule to improve readability.
    symabis_digest = None
    if resolved_package.s_files:
        # From Go tooling comments:
        # 	// Supply an empty go_asm.h as if the compiler had been run.
        # 	// -symabis parsing is lax enough that we don't need the
        # 	// actual definitions that would appear in go_asm.h.
        # See https://go-review.googlesource.com/c/go/+/146999/8/src/cmd/go/internal/work/gc.go
        go_asm_h_digest = await Get(
            Digest, CreateDigest([FileContent(path="go_asm.h", content=b"")])
        )
        gensymabis_input_digest = await Get(Digest, MergeDigests([input_digest, go_asm_h_digest]))
        gensymabis_result = await Get(
            ProcessResult,
            GoSdkProcess(
                input_digest=gensymabis_input_digest,
                command=(
                    "tool",
                    "asm",
                    "-I",
                    "go/pkg/include",  # NOTE: points into GOROOT; assumption inferred from rules_go and Go tooling
                    "-gensymabis",
                    "-o",
                    "gensymabis",
                    "--",
                    *(f"./{source_files_subpath}/{name}" for name in resolved_package.s_files),
                ),
                description="Generate gensymabis metadata for assemnbly files.",
                output_files=("gensymabis",),
            ),
        )
        symabis_digest = gensymabis_result.output_digest

    compile_command = [
        "tool",
        "compile",
        "-p",
        import_path,
        "-importcfg",
        "./importcfg",
        "-pack",
        "-o",
        "__pkg__.a",
    ]
    if symabis_digest:
        compile_command.extend(["-symabis", "./gensymabis"])
        input_digest = await Get(
            Digest,
            MergeDigests([input_digest, symabis_digest]),
        )
    compile_command.append("--")
    compile_command.extend(f"./{source_files_subpath}/{name}" for name in resolved_package.go_files)

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=tuple(compile_command),
            description=f"Compile Go package with {pluralize(len(resolved_package.go_files), 'file')}. [{request.address}]",
            output_files=("__pkg__.a",),
        ),
    )
    output_digest = result.output_digest

    # Assemble any .s files and merge into the package archive.
    # TODO(12762): Refactor to separate rule to improve readability.
    if resolved_package.s_files:
        # Assemble
        asm_requests = [
            Get(
                ProcessResult,
                GoSdkProcess(
                    input_digest=input_digest,
                    command=(
                        "tool",
                        "asm",
                        "-I",
                        "go/pkg/include",  # NOTE: points into GOROOT; assumption inferred from rules_go and Go tooling
                        "-o",
                        f"./{source_files_subpath}/{PurePath(s_file).with_suffix('.o')}",
                        f"./{source_files_subpath}/{s_file}",
                    ),
                    description=f"Assemble Go .s file [{request.address}]",
                    output_files=(
                        f"./{source_files_subpath}/{PurePath(s_file).with_suffix('.o')}",
                    ),
                ),
            )
            for s_file in resolved_package.s_files
        ]
        asm_results = await MultiGet(asm_requests)
        merged_asm_output_digest = await Get(
            Digest, MergeDigests([output_digest] + [r.output_digest for r in asm_results])
        )

        # Link into package archive.
        pack_result = await Get(
            ProcessResult,
            GoSdkProcess(
                input_digest=merged_asm_output_digest,
                command=(
                    "tool",
                    "pack",
                    "r",
                    "__pkg__.a",
                    *(
                        f"./{source_files_subpath}/{PurePath(name).with_suffix('.o')}"
                        for name in resolved_package.s_files
                    ),
                ),
                description="Add assembly files to Go package archive.",
                output_files=("__pkg__.a",),
            ),
        )
        output_digest = pack_result.output_digest

    return BuiltGoPackage(import_path=import_path, object_digest=output_digest)


@rule
async def package_go_binary(
    field_set: GoBinaryFieldSet,
) -> BuiltPackage:
    main_address = field_set.main_address.value or ""
    main_go_package_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(main_address, relative_to=field_set.address.spec_path),
    )
    wrapped_main_go_package_target = await Get(WrappedTarget, Address, main_go_package_address)
    main_go_package_target = wrapped_main_go_package_target.target
    built_main_go_package = await Get(
        BuiltGoPackage, BuildGoPackageRequest(address=main_go_package_target.address, is_main=True)
    )

    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(roots=[main_go_package_target.address])
    )
    buildable_deps = [
        tgt
        for tgt in transitive_targets.dependencies
        if is_first_party_package_target(tgt) or is_third_party_package_target(tgt)
    ]

    built_transitive_go_deps_requests = [
        Get(BuiltGoPackage, BuildGoPackageRequest(address=tgt.address)) for tgt in buildable_deps
    ]
    built_transitive_go_deps = await MultiGet(built_transitive_go_deps_requests)

    gathered_imports = await Get(
        GatheredImports,
        GatherImportsRequest(
            packages=FrozenOrderedSet(built_transitive_go_deps),
            include_stdlib=True,
        ),
    )

    input_digest = await Get(
        Digest, MergeDigests([gathered_imports.digest, built_main_go_package.object_digest])
    )

    output_filename = PurePath(field_set.output_path.value_or_default(file_ending=None))
    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=(
                "tool",
                "link",
                "-importcfg",
                "./importcfg",
                "-o",
                f"./{output_filename.name}",
                "-buildmode=exe",  # seen in `go build -x` output
                "./__pkg__.a",
            ),
            description="Link Go binary.",
            output_files=(f"./{output_filename.name}",),
        ),
    )

    renamed_output_digest = await Get(
        Digest, AddPrefix(result.output_digest, str(output_filename.parent))
    )

    artifact = BuiltPackageArtifact(relpath=str(output_filename))
    return BuiltPackage(digest=renamed_output_digest, artifacts=(artifact,))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, GoBinaryFieldSet),
    ]
