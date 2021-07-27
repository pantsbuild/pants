# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import logging
import textwrap
import typing
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.go.distribution import GoLangDistribution
from pants.backend.go.module import (
    FindOwningGoModuleRequest,
    ResolvedGoModule,
    ResolvedOwningGoModule,
    ResolveGoModuleRequest,
)
from pants.backend.go.target_types import GoImportPath, GoModuleSources, GoPackageSources
from pants.build_graph.address import Address
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import UnexpandedTargets
from pants.util.logging import LogLevel

_logger = logging.getLogger(__name__)


# A fully-resolved Go package. The metadata is obtained by invoking `go list` on the package.
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
    goroot: GoLangDistribution,
    platform: Platform,
    bash: BashBinary,
) -> ResolvedGoPackage:
    # TODO: Use MultiGet where applicable.

    downloaded_goroot = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        goroot.get_request(platform),
    )

    targets = await Get(UnexpandedTargets, Addresses([request.address]))
    if not targets:
        raise AssertionError(f"Address `{request.address}` did not resolve to any targets.")
    elif len(targets) > 1:
        raise AssertionError(f"Address `{request.address}` resolved to multiple targets.")
    target = targets[0]

    owning_go_module_result = await Get(
        ResolvedOwningGoModule, FindOwningGoModuleRequest(request.address)
    )

    if not owning_go_module_result.module_address:
        raise ValueError(f"The go_package at address {request.address} has no owning go_module.")
    resolved_go_module = await Get(
        ResolvedGoModule, ResolveGoModuleRequest(owning_go_module_result.module_address)
    )
    assert request.address.spec_path.startswith(resolved_go_module.address.spec_path)
    spec_subpath = request.address.spec_path[len(resolved_go_module.address.spec_path) :]

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
                f"because the owning go_module at address {resolved_go_module.address} "
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

    # Note: The `go` tool requires GOPATH to be an absolute path which can only be resolved from within the
    # execution sandbox. Thus, this code uses a bash script to be able to resolve that path.
    # TODO: Merge all duplicate versions of this script into a single script and add an invoke rule that will
    # insert the desired `go` command into the boilerplate portions.
    analyze_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "analyze.sh",
                    textwrap.dedent(
                        f"""\
                export GOROOT="$(/bin/pwd)/go"
                export GOPATH="$(/bin/pwd)/gopath"
                export GOCACHE="$(/bin/pwd)/cache"
                /bin/mkdir -p "$GOPATH" "$GOCACHE"
                cd {resolved_go_module.address.spec_path}
                exec "${{GOROOT}}/bin/go" list -json ./{spec_subpath}
                """
                    ).encode("utf-8"),
                )
            ]
        ),
    )

    input_root_digest = await Get(
        Digest,
        MergeDigests([sources.snapshot.digest, downloaded_goroot.digest, analyze_script_digest]),
    )

    process = Process(
        argv=[bash.path, "./analyze.sh"],
        input_digest=input_root_digest,
        description="Resolve go_package metadata.",
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)

    metadata = json.loads(result.stdout)

    # TODO: Raise an exception on errors. They are only emitted as warnings for now because the `go` tool is
    # flagging missing first-party code as a dependency error. But we want dependency inference and won't know
    # what the dependency actually is unless we first resolve the package with that dependency. So circular
    # reasoning. We may need to hydrate the sources for all go_package targets that share a `go_module`.
    if metadata.get("Incomplete"):
        error_dict = metadata.get("Error", {})
        if error_dict:
            error_str = error_to_string(error_dict)
            _logger.warning(
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

    package_name: str = metadata["Name"]
    imports = typing.cast(Tuple[str, ...], tuple(metadata.get("Imports", [])))
    test_imports = typing.cast(Tuple[str, ...], tuple(metadata.get("TestImports", [])))
    dependency_import_paths = typing.cast(Tuple[str, ...], tuple(metadata.get("Deps", [])))
    go_files = typing.cast(Tuple[str, ...], tuple(metadata.get("GoFiles", [])))
    cgo_files = typing.cast(Tuple[str, ...], tuple(metadata.get("CgoFiles", [])))
    ignored_go_files = typing.cast(Tuple[str, ...], tuple(metadata.get("IgnoredGoFiles", [])))
    ignored_other_files = typing.cast(Tuple[str, ...], tuple(metadata.get("IgnoredOtherFiles", [])))
    test_go_files = typing.cast(Tuple[str, ...], tuple(metadata.get("TestGoFiles", [])))
    xtest_go_files = typing.cast(Tuple[str, ...], tuple(metadata.get("XTestGoFiles", [])))

    return ResolvedGoPackage(
        address=request.address,
        import_path=import_path,
        module_address=owning_go_module_result.module_address,
        package_name=package_name,
        imports=imports,
        test_imports=test_imports,
        dependency_import_paths=dependency_import_paths,
        go_files=go_files,
        cgo_files=cgo_files,
        ignored_go_files=ignored_go_files,
        ignored_other_files=ignored_other_files,
        test_go_files=test_go_files,
        xtest_go_files=xtest_go_files,
    )


def rules():
    return collect_rules()
