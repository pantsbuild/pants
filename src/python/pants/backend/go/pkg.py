# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import ijson

from pants.backend.go.module import (
    DownloadedExternalModule,
    DownloadExternalModuleRequest,
    FindNearestGoModuleRequest,
    ResolvedGoModule,
    ResolvedOwningGoModule,
    ResolveGoModuleRequest,
)
from pants.backend.go.sdk import GoSdkProcess
from pants.backend.go.target_types import (
    GoExternalModulePathField,
    GoExternalModuleVersionField,
    GoExternalPackageDependencies,
    GoExternalPackageImportPathField,
    GoImportPath,
    GoModuleSources,
    GoPackageSources,
)
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.console import Console
from pants.engine.fs import (
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    GlobExpansionConjunction,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import Target, UnexpandedTargets, WrappedTarget
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

logger = logging.getLogger(__name__)


# A fully-resolved Go package. The metadata is obtained by invoking `go list` on the package.
# TODO: Add class docstring with info on the fields.
# TODO: Consider renaming some of these fields once use of this class has stabilized.
@dataclass(frozen=True)
class ResolvedGoPackage:
    # Address of the `go_package` target (if any).
    address: Address | None

    # Import path of this package. The import path will be inferred from an owning `go_module` if present.
    import_path: str

    # Address of the owning `go_module` if present. The owning `go_module` is the nearest go_module at the same
    # or higher level of the source tree.
    module_address: Address | None

    # External module information
    module_path: str | None
    module_version: str | None

    # Name of the package as given by `package` directives in the source files. Obtained from `Name` key in
    # package metadata.
    package_name: str

    # Import paths used by this package. Obtained from `Imports` key in package metadata.
    imports: tuple[str, ...]

    # Imports from test files. Obtained from `TestImports` key in package metadata.
    test_imports: tuple[str, ...]

    # Explicit and transitive import paths required to build the code. Obtained from `Deps` key in package metadata.
    dependency_import_paths: tuple[str, ...]

    # .go source files (excluding CgoFiles, TestGoFiles, XTestGoFiles). Obtained from `GoFiles` key in package metadata.
    go_files: tuple[str, ...]

    # .go source files that import "C". Obtained from `CgoFiles` key in package metadata.
    cgo_files: tuple[str, ...]

    # .go source files ignored due to build constraints. Obtained from `IgnoredGoFiles` key in package metadata.
    ignored_go_files: tuple[str, ...]

    # non-.go source files ignored due to build constraints. Obtained from `IgnoredOtherFiles` key in package metadata.
    ignored_other_files: tuple[str, ...]

    # .c source files
    c_files: tuple[str, ...]

    # .cc, .cxx and .cpp source files
    cxx_files: tuple[str, ...]

    # .m source files
    m_files: tuple[str, ...]

    # .h, .hh, .hpp and .hxx source files
    h_files: tuple[str, ...]

    # .s source files
    s_files: tuple[str, ...]

    # .syso object files to add to archive
    syso_files: tuple[str, ...]

    # _test.go files in package. Obtained from `TestGoFiles` key in package metadata.
    test_go_files: tuple[str, ...]

    # _test.go files outside package. Obtained from `XTestGoFiles` key in package metadata.
    xtest_go_files: tuple[str, ...]

    @classmethod
    def from_metadata(
        cls,
        metadata: dict,
        *,
        import_path: str | None = None,
        address: Address | None = None,
        module_address: Address | None = None,
        module_path: str | None = None,
        module_version: str | None = None,
    ) -> ResolvedGoPackage:
        # TODO: Raise an exception on errors. They are only emitted as warnings for now because the `go` tool is
        # flagging missing first-party code as a dependency error. But we want dependency inference and won't know
        # what the dependency actually is unless we first resolve the package with that dependency. So circular
        # reasoning. We may need to hydrate the sources for all go_package targets that share a `go_module`.
        if metadata.get("Incomplete"):
            error_dict = metadata.get("Error", {})
            if error_dict:
                error_str = error_to_string(error_dict)
                logger.warning(
                    f"Error while resolving Go package at address {address}: {error_str}"
                )
            # TODO: Check DepsErrors key as well.

        # Raise an exception if any unsupported source file keys are present in the metadata.
        for key in (
            "CompiledGoFiles",
            "FFiles",
            "SwigFiles",
            "SwigCXXFiles",
        ):
            files = metadata.get(key, [])
            package_description = (
                f"go_package at address {address}"
                if address
                else f"external package at import path {import_path} in {module_path}@{module_version}"
            )
            if files:
                raise ValueError(
                    f"The {package_description} contains the following unsupported source files "
                    f"that were detected under the key '{key}': {', '.join(files)}."
                )

        return cls(
            address=address,
            import_path=import_path if import_path is not None else metadata["ImportPath"],
            module_address=module_address,
            module_path=module_path,
            module_version=module_version,
            package_name=metadata["Name"],
            imports=tuple(metadata.get("Imports", [])),
            test_imports=tuple(metadata.get("TestImports", [])),
            dependency_import_paths=tuple(metadata.get("Deps", [])),
            go_files=tuple(metadata.get("GoFiles", [])),
            cgo_files=tuple(metadata.get("CgoFiles", [])),
            ignored_go_files=tuple(metadata.get("IgnoredGoFiles", [])),
            ignored_other_files=tuple(metadata.get("IgnoredOtherFiles", [])),
            c_files=tuple(metadata.get("CFiles", [])),
            cxx_files=tuple(metadata.get("CXXFiles", [])),
            m_files=tuple(metadata.get("MFiles", [])),
            h_files=tuple(metadata.get("HFiles", [])),
            s_files=tuple(metadata.get("SFiles", [])),
            syso_files=tuple(metadata.get("SysoFiles", [])),
            test_go_files=tuple(metadata.get("TestGoFiles", [])),
            xtest_go_files=tuple(metadata.get("XTestGoFiles", [])),
        )


@dataclass(frozen=True)
class ResolveGoPackageRequest:
    address: Address


@dataclass(frozen=True)
class ResolveExternalGoPackageRequest:
    address: Address


def error_to_string(d: dict) -> str:
    pos = d.get("Pos", "")
    if pos:
        pos = f"{pos}: "

    import_stack_items = d.get("ImportStack", [])
    import_stack = f" (import stack: {', '.join(import_stack_items)})" if import_stack_items else ""
    return f"{pos}{d['Err']}{import_stack}"


def is_first_party_package_target(tgt: Target) -> bool:
    return tgt.has_field(GoPackageSources)


def is_third_party_package_target(tgt: Target) -> bool:
    return tgt.has_field(GoExternalPackageDependencies)


@rule
async def resolve_go_package(
    request: ResolveGoPackageRequest,
) -> ResolvedGoPackage:
    wrapped_target, owning_go_module_result = await MultiGet(
        Get(WrappedTarget, Address, request.address),
        Get(ResolvedOwningGoModule, FindNearestGoModuleRequest(request.address.spec_path)),
    )
    target = wrapped_target.target

    if not owning_go_module_result.module_address:
        raise ValueError(f"The go_package at address {request.address} has no owning go_module.")
    resolved_go_module = await Get(
        ResolvedGoModule, ResolveGoModuleRequest(owning_go_module_result.module_address)
    )
    go_module_spec_path = resolved_go_module.target.address.spec_path
    assert request.address.spec_path.startswith(go_module_spec_path)
    spec_subpath = request.address.spec_path[len(go_module_spec_path) :]

    # Compute the import_path for this go_package.
    import_path_field = target.get(GoImportPath)
    if import_path_field and import_path_field.value:
        # Use any explicit import path set on the `go_package` target.
        import_path = import_path_field.value
    else:
        # Otherwise infer the import path from the owning `go_module` target. The inferred import path will be the
        # module's import path plus any subdirectories in the spec_path between the go_module and go_package target.
        if not resolved_go_module.import_path:
            raise ValueError(
                f"Unable to infer import path for the `go_package` at address {request.address} "
                f"because the owning go_module at address {resolved_go_module.target.address} "
                "does not have an import path defined nor could one be inferred."
            )
        import_path = f"{resolved_go_module.import_path}/"
        if spec_subpath.startswith("/"):
            import_path += spec_subpath[1:]
        else:
            import_path += spec_subpath

    sources = await Get(
        SourceFiles,
        SourceFilesRequest(
            [
                target.get(GoPackageSources),
                resolved_go_module.target.get(GoModuleSources),
            ]
        ),
    )

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=sources.snapshot.digest,
            command=("list", "-json", f"./{spec_subpath}"),
            description="Resolve go_package metadata.",
            working_dir=resolved_go_module.target.address.spec_path,
        ),
    )

    metadata = json.loads(result.stdout)
    return ResolvedGoPackage.from_metadata(
        metadata,
        import_path=import_path,
        address=request.address,
        module_address=owning_go_module_result.module_address,
    )


@rule
async def resolve_external_go_package(
    request: ResolveExternalGoPackageRequest,
) -> ResolvedGoPackage:
    wrapped_target = await Get(WrappedTarget, Address, request.address)
    target = wrapped_target.target

    import_path = target[GoExternalPackageImportPathField].value
    module_path = target[GoExternalModulePathField].value
    module_version = target[GoExternalModuleVersionField].value

    module = await Get(
        DownloadedExternalModule,
        DownloadExternalModuleRequest(
            path=module_path,
            version=module_version,
        ),
    )

    assert import_path.startswith(module_path)
    subpath = import_path[len(module_path) :]

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=module.digest,
            command=("list", "-json", f"./{subpath}"),
            description="Resolve _go_external_package metadata.",
        ),
    )

    metadata = json.loads(result.stdout)
    return ResolvedGoPackage.from_metadata(
        metadata,
        import_path=import_path,
        address=request.address,
        module_address=None,
        module_path=module_path,
        module_version=module_version,
    )


@dataclass(frozen=True)
class ResolveExternalGoModuleToPackagesRequest:
    path: str
    version: str
    go_sum_digest: Digest


@dataclass(frozen=True)
class ResolveExternalGoModuleToPackagesResult:
    # TODO: Consider using DeduplicatedCollection if this is the only field.
    packages: FrozenOrderedSet[ResolvedGoPackage]


@rule
async def resolve_external_module_to_go_packages(
    request: ResolveExternalGoModuleToPackagesRequest,
) -> ResolveExternalGoModuleToPackagesResult:
    module_path = request.path
    assert module_path
    module_version = request.version
    assert module_version

    downloaded_module = await Get(
        DownloadedExternalModule,
        DownloadExternalModuleRequest(path=module_path, version=module_version),
    )
    sources_digest = await Get(Digest, AddPrefix(downloaded_module.digest, "__sources__"))

    # TODO: Super hacky merge of go.sum from both digests. We should really just pass in the fully-resolved
    # go.sum and use that, but this allows the go.sum from the downloaded module to have some effect. Not sure
    # if that is right call, but hackity hack!
    left_digest_contents = await Get(DigestContents, Digest, sources_digest)
    left_go_sum_contents = b""
    for fc in left_digest_contents:
        if fc.path == "__sources__/go.sum":
            left_go_sum_contents = fc.content
            break

    go_sum_only_digest = await Get(
        Digest, DigestSubset(request.go_sum_digest, PathGlobs(["go.sum"]))
    )
    go_sum_prefixed_digest = await Get(Digest, AddPrefix(go_sum_only_digest, "__sources__"))
    right_digest_contents = await Get(DigestContents, Digest, go_sum_prefixed_digest)
    right_go_sum_contents = b""
    for fc in right_digest_contents:
        if fc.path == "__sources__/go.sum":
            right_go_sum_contents = fc.content
            break
    go_sum_contents = left_go_sum_contents + b"\n" + right_go_sum_contents
    go_sum_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    path="__sources__/go.sum",
                    content=go_sum_contents,
                )
            ]
        ),
    )

    sources_digest_no_go_sum = await Get(
        Digest,
        DigestSubset(
            sources_digest,
            PathGlobs(
                ["!__sources__/go.sum", "__sources__/**"],
                conjunction=GlobExpansionConjunction.all_match,
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin="FUNKY",
            ),
        ),
    )

    input_digest = await Get(Digest, MergeDigests([sources_digest_no_go_sum, go_sum_digest]))

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=("list", "-json", "./..."),
            working_dir="__sources__",
            description=f"Resolve packages in Go external module {module_path}@{module_version}",
        ),
    )

    packages: OrderedSet[ResolvedGoPackage] = OrderedSet()
    for metadata in ijson.items(result.stdout, "", multiple_values=True):
        package = ResolvedGoPackage.from_metadata(
            metadata, module_path=module_path, module_version=module_version
        )
        packages.add(package)

    return ResolveExternalGoModuleToPackagesResult(packages=FrozenOrderedSet(packages))


class GoPkgDebugSubsystem(GoalSubsystem):
    name = "go-pkg-debug"
    help = "Resolve a Go package and display its metadata"


class GoPkgDebugGoal(Goal):
    subsystem_cls = GoPkgDebugSubsystem


@goal_rule
async def run_go_pkg_debug(targets: UnexpandedTargets, console: Console) -> GoPkgDebugGoal:
    first_party_package_targets = [tgt for tgt in targets if is_first_party_package_target(tgt)]
    first_party_requests = [
        Get(ResolvedGoPackage, ResolveGoPackageRequest(address=tgt.address))
        for tgt in first_party_package_targets
    ]

    third_party_package_targets = [tgt for tgt in targets if is_third_party_package_target(tgt)]
    third_party_requests = [
        Get(ResolvedGoPackage, ResolveExternalGoPackageRequest(address=tgt.address))
        for tgt in third_party_package_targets
    ]

    resolved_packages = await MultiGet([*first_party_requests, *third_party_requests])  # type: ignore
    for package in resolved_packages:
        console.write_stdout(str(package) + "\n")

    return GoPkgDebugGoal(exit_code=0)


def rules():
    return collect_rules()
