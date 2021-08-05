# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.go.module import (
    FindNearestGoModuleRequest,
    ResolvedGoModule,
    ResolvedOwningGoModule,
    ResolveGoModuleRequest,
)
from pants.backend.go.sdk import GoSdkProcess
from pants.backend.go.target_types import GoImportPath, GoModuleSources, GoPackageSources
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import UnexpandedTargets

logger = logging.getLogger(__name__)


# A fully-resolved Go package. The metadata is obtained by invoking `go list` on the package.
# TODO: Add class docstring with info on the fields.
@dataclass(frozen=True)
class ResolvedGoPackage:
    # Address of the `go_package` target. Copied from the `ResolveGoPackageRequest` for ease of access.
    address: Address

    # Import path of this package. The import path will be inferred from an owning `go_module` if present.
    import_path: str

    # Address of the owning `go_module` if present. The owning `go_module` is the nearest go_module at the same
    # or higher level of the source tree.
    module_address: Optional[Address]

    # Name of the package as given by `package` directives in the source files. Obtained from `Name` key in
    # package metadata.
    package_name: str

    # Import paths used by this package. Obtained from `Imports` key in package metadata.
    imports: Tuple[str, ...]

    # Imports from test files. Obtained from `TestImports` key in package metadata.
    test_imports: Tuple[str, ...]

    # Explicit and transitive import paths required to build the code. Obtained from `Deps` key in package metadata.
    dependency_import_paths: Tuple[str, ...]

    # .go source files (excluding CgoFiles, TestGoFiles, XTestGoFiles). Obtained from `GoFiles` key in package metadata.
    go_files: Tuple[str, ...]

    # .go source files that import "C". Obtained from `CgoFiles` key in package metadata.
    cgo_files: Tuple[str, ...]

    # .go source files ignored due to build constraints. Obtained from `IgnoredGoFiles` key in package metadata.
    ignored_go_files: Tuple[str, ...]

    # non-.go source files ignored due to build constraints. Obtained from `IgnoredOtherFiles` key in package metadata.
    ignored_other_files: Tuple[str, ...]

    # _test.go files in package. Obtained from `TestGoFiles` key in package metadata.
    test_go_files: Tuple[str, ...]

    # _test.go files outside package. Obtained from `XTestGoFiles` key in package metadata.
    xtest_go_files: Tuple[str, ...]


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


@rule
async def resolve_go_package(
    request: ResolveGoPackageRequest,
    platform: Platform,
    bash: BashBinary,
) -> ResolvedGoPackage:
    # TODO: Use MultiGet where applicable.

    targets = await Get(UnexpandedTargets, Addresses([request.address]))
    if not targets:
        raise AssertionError(f"Address `{request.address}` did not resolve to any targets.")
    elif len(targets) > 1:
        raise AssertionError(f"Address `{request.address}` resolved to multiple targets.")
    target = targets[0]

    owning_go_module_result = await Get(
        ResolvedOwningGoModule, FindNearestGoModuleRequest(request.address.spec_path)
    )

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
        import_path = f"{resolved_go_module.import_path}{spec_subpath}"

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

    # TODO: Raise an exception on errors. They are only emitted as warnings for now because the `go` tool is
    # flagging missing first-party code as a dependency error. But we want dependency inference and won't know
    # what the dependency actually is unless we first resolve the package with that dependency. So circular
    # reasoning. We may need to hydrate the sources for all go_package targets that share a `go_module`.
    if metadata.get("Incomplete"):
        error_dict = metadata.get("Error", {})
        if error_dict:
            error_str = error_to_string(error_dict)
            logger.warning(
                f"Error while resolving Go package at address {request.address}: {error_str}"
            )
        # TODO: Check DepsErrors key as well.

    # Raise an exception if any unsupported source file keys are present in the metadata.
    for key in (
        "CompiledGoFiles",
        "CFiles",
        "CXXFiles",
        "MFiles",
        "HFiles",
        "FFiles",
        "SFiles",
        "SwigFiles",
        "SwigCXXFiles",
        "SysoFiles",
    ):
        files = metadata.get(key, [])
        if files:
            raise ValueError(
                f"The go_package at address {request.address} contains the following unsupported source files "
                f"that were detected under the key '{key}': {', '.join(files)}."
            )

    return ResolvedGoPackage(
        address=request.address,
        import_path=import_path,
        module_address=owning_go_module_result.module_address,
        package_name=metadata["Name"],
        imports=tuple(metadata.get("Imports", [])),
        test_imports=tuple(metadata.get("TestImports", [])),
        dependency_import_paths=tuple(metadata.get("Deps", [])),
        go_files=tuple(metadata.get("GoFiles", [])),
        cgo_files=tuple(metadata.get("CgoFiles", [])),
        ignored_go_files=tuple(metadata.get("IgnoredGoFiles", [])),
        ignored_other_files=tuple(metadata.get("IgnoredOtherFiles", [])),
        test_go_files=tuple(metadata.get("TestGoFiles", [])),
        xtest_go_files=tuple(metadata.get("XTestGoFiles", [])),
    )


def rules():
    return collect_rules()
