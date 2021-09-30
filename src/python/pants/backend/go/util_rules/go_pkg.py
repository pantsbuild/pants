# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoExternalPackageDependencies,
    GoImportPath,
    GoPackageSources,
)
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.build_graph.address import Address
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest, Target, WrappedTarget

logger = logging.getLogger(__name__)


# A fully-resolved Go package. The metadata is obtained by invoking `go list` on the package.
# TODO: Add class docstring with info on the fields.
# TODO: Consider renaming some of these fields once use of this class has stabilized.
@dataclass(frozen=True)
class ResolvedGoPackage:
    # Address of the `go_package` target (if any).
    address: Address | None

    # Import path of this package. The import path will be inferred from an owning `go_mod` if present.
    import_path: str

    # Address of the owning `go_mod` if present. The owning `go_mod` is the nearest go_mod at the same
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
        # reasoning. We may need to hydrate the sources for all go_package targets that share a `go_mod`.
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
    wrapped_target, owning_go_mod = await MultiGet(
        Get(WrappedTarget, Address, request.address),
        Get(OwningGoMod, OwningGoModRequest(request.address)),
    )
    target = wrapped_target.target

    go_mod_spec_path = owning_go_mod.address.spec_path
    assert request.address.spec_path.startswith(go_mod_spec_path)
    spec_subpath = request.address.spec_path[len(go_mod_spec_path) :]

    go_mod_info, pkg_sources = await MultiGet(
        Get(GoModInfo, GoModInfoRequest(owning_go_mod.address)),
        Get(HydratedSources, HydrateSourcesRequest(target[GoPackageSources])),
    )
    input_digest = await Get(
        Digest, MergeDigests([pkg_sources.snapshot.digest, go_mod_info.digest])
    )

    # Compute the import_path for this go_package.
    import_path_field = target.get(GoImportPath)
    if import_path_field and import_path_field.value:
        # Use any explicit import path set on the `go_package` target.
        import_path = import_path_field.value
    else:
        # Otherwise infer the import path from the owning `go_mod` target. The inferred import
        # path will be the module's import path plus any subdirectories in the spec_path
        # between the go_mod and go_package target.
        import_path = f"{go_mod_info.import_path}/"
        if spec_subpath.startswith("/"):
            import_path += spec_subpath[1:]
        else:
            import_path += spec_subpath

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=("list", "-json", f"./{spec_subpath}"),
            description="Resolve go_package metadata.",
            working_dir=go_mod_spec_path,
        ),
    )

    metadata = json.loads(result.stdout)
    return ResolvedGoPackage.from_metadata(
        metadata,
        import_path=import_path,
        address=request.address,
        module_address=owning_go_mod.address,
    )


def rules():
    return collect_rules()
