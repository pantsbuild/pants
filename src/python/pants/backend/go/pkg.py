# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
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
from pants.backend.go.target_types import GoImportPath, GoModuleSources
from pants.build_graph.address import Address
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, RemovePrefix, Snapshot
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import UnexpandedTargets
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class ResolvedGoPackage:
    address: Address
    import_path: str
    module_address: Optional[Address]
    package_name: str
    imported_import_paths: Tuple[str]
    dependency_import_paths: Tuple[str]


@dataclass(frozen=True)
class ResolveGoPackageRequest:
    address: Address


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

    # Compute the import_path for this go_package.
    import_path_field = target.get(GoImportPath)
    if import_path_field and import_path_field.value:
        # Use any explicit import path set on the `go_package` target.
        import_path = import_path_field.value
    elif owning_go_module_result.module_address:
        # Otherwise infer the import path from the owning `go_module` target. The inferred import path will be the
        # module's import path plus any subdirectories in the spec_path between the go_module and go_package target.
        resolved_go_module = await Get(
            ResolvedGoModule, ResolveGoModuleRequest(owning_go_module_result.module_address)
        )
        if not resolved_go_module.import_path:
            raise ValueError(
                f"Unable to infer import path for the `go_package` at address {request.address} "
                f"because the owning go_module at address {resolved_go_module.address} "
                "does not have an import path defined."
            )
        assert request.address.spec_path.startswith(resolved_go_module.address.spec_path)
        spec_path_difference = request.address.spec_path[
            len(resolved_go_module.address.spec_path) :
        ]
        import_path = f"{resolved_go_module.import_path}{spec_path_difference}"
    else:
        raise ValueError(
            f"Unable to infer import path for the `go_package` at address {request.address} "
            "because no owning go_module was found (which would define an import path for the module) "
            "and no explicit `import_path` was set on the go_package"
        )

    sources = await Get(SourceFiles, SourceFilesRequest([target.get(GoModuleSources)]))
    flattened_sources_snapshot = await Get(
        Snapshot, RemovePrefix(sources.snapshot.digest, request.address.spec_path)
    )

    # Note: The `go` tool requires GOPATH to be an absolute path which can only be resolved from within the
    # execution sandbox. Thus, this code uses a bash script to be able to resolve that path.
    # TODO: Merge all duplicate versions of this script into a single script and invoke rule.
    analyze_script_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "analyze.sh",
                    textwrap.dedent(
                        """\
                export GOROOT="./go"
                export GOPATH="$(/bin/pwd)/gopath"
                export GOCACHE="$(/bin/pwd)/cache"
                mkdir -p "$GOPATH" "$GOCACHE"
                exec ./go/bin/go list -json .
                """
                    ).encode("utf-8"),
                )
            ]
        ),
    )

    input_root_digest = await Get(
        Digest,
        MergeDigests(
            [flattened_sources_snapshot.digest, downloaded_goroot.digest, analyze_script_digest]
        ),
    )

    process = Process(
        argv=[bash.path, "./analyze.sh"],
        input_digest=input_root_digest,
        description="Resolve go_package metadata.",
        output_files=["go.mod", "go.sum"],
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)
    print(f"stdout={result.stdout}")  # type: ignore[str-bytes-safe]
    print(f"stderr={result.stderr}")  # type: ignore[str-bytes-safe]

    metadata = json.loads(result.stdout)
    package_name: str = metadata["Name"]
    imported_import_paths = typing.cast(Tuple[str], tuple(metadata["Imports"]))
    dependency_import_paths = typing.cast(Tuple[str], tuple(metadata["Deps"]))

    return ResolvedGoPackage(
        address=request.address,
        import_path=import_path,
        module_address=owning_go_module_result.module_address,
        package_name=package_name,
        imported_import_paths=imported_import_paths,
        dependency_import_paths=dependency_import_paths,
    )


def rules():
    return collect_rules()
