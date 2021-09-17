# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional

import ijson

from pants.backend.go.sdk import GoSdkProcess
from pants.backend.go.target_types import GoModuleSources
from pants.base.specs import AddressSpecs, AscendantAddresses, MaybeEmptySiblingAddresses
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target, UnexpandedTargets, WrappedTarget
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleDescriptor:
    path: str
    version: str


# TODO: Add class docstring with info on the fields.
@dataclass(frozen=True)
class ResolvedGoModule:
    # The go_module target.
    target: Target

    # Import path of the Go module. Inferred from the import path in the go.mod file.
    import_path: str

    # Minimum Go version of the module from `go` statement in go.mod.
    minimum_go_version: Optional[str]

    # Modules referenced by this go.mod with resolved versions.
    modules: FrozenOrderedSet[ModuleDescriptor]

    # Digest containing go.mod and updated go.sum.
    digest: Digest


@dataclass(frozen=True)
class ResolveGoModuleRequest:
    address: Address


# Parse the output of `go mod download` into a list of module descriptors.
def parse_module_descriptors(raw_json: bytes) -> List[ModuleDescriptor]:
    # `ijson` cannot handle empty input so short-circuit if there is no data.
    if len(raw_json) == 0:
        return []

    module_descriptors = []
    for raw_module_descriptor in ijson.items(raw_json, "", multiple_values=True):
        # Skip listing the main module.
        if raw_module_descriptor.get("Main", False):
            continue

        module_descriptor = ModuleDescriptor(
            path=raw_module_descriptor["Path"],
            version=raw_module_descriptor["Version"],
        )
        module_descriptors.append(module_descriptor)
    return module_descriptors


@rule
async def resolve_go_module(
    request: ResolveGoModuleRequest,
) -> ResolvedGoModule:
    wrapped_target = await Get(WrappedTarget, Address, request.address)
    target = wrapped_target.target

    sources = await Get(SourceFiles, SourceFilesRequest([target.get(GoModuleSources)]))
    flattened_sources_snapshot = await Get(
        Snapshot, RemovePrefix(sources.snapshot.digest, request.address.spec_path)
    )

    # Parse the go.mod for the module path and minimum Go version.
    parse_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=flattened_sources_snapshot.digest,
            command=("mod", "edit", "-json"),
            description=f"Parse go.mod for {request.address}.",
        ),
    )
    module_metadata = json.loads(parse_result.stdout)
    module_path = module_metadata["Module"]["Path"]
    minimum_go_version = module_metadata.get(
        "Go", "1.16"
    )  # TODO: Figure out better default if missing. Use the SDKs version versus this hard-code.

    # Resolve the dependencies in the go.mod.
    list_modules_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=flattened_sources_snapshot.digest,
            command=("list", "-m", "-json", "all"),
            description=f"List modules in build of {request.address}.",
        ),
    )
    modules = parse_module_descriptors(list_modules_result.stdout)

    return ResolvedGoModule(
        target=target,
        import_path=module_path,
        minimum_go_version=minimum_go_version,
        modules=FrozenOrderedSet(modules),
        digest=flattened_sources_snapshot.digest,  # TODO: Is this a resolved version? Need to update for go-resolve goal?
    )


@dataclass(frozen=True)
class FindNearestGoModuleRequest:
    spec_path: str


@dataclass(frozen=True)
class ResolvedOwningGoModule:
    module_address: Optional[Address]


@rule
async def find_nearest_go_module(request: FindNearestGoModuleRequest) -> ResolvedOwningGoModule:
    spec_path = request.spec_path
    candidate_targets = await Get(
        UnexpandedTargets,
        AddressSpecs([AscendantAddresses(spec_path), MaybeEmptySiblingAddresses(spec_path)]),
    )
    go_module_targets = [tgt for tgt in candidate_targets if tgt.has_field(GoModuleSources)]

    # Sort by address.spec_path in descending order so the nearest go_module target is sorted first.
    sorted_go_module_targets = sorted(
        go_module_targets, key=lambda tgt: tgt.address.spec_path, reverse=True
    )
    if sorted_go_module_targets:
        nearest_go_module_target = sorted_go_module_targets[0]
        return ResolvedOwningGoModule(module_address=nearest_go_module_target.address)
    else:
        # TODO: Consider eventually requiring all go_package's to associate with a go_module.
        return ResolvedOwningGoModule(module_address=None)


@dataclass(frozen=True)
class DownloadExternalModuleRequest:
    path: str
    version: str


@dataclass(frozen=True)
class DownloadedExternalModule:
    path: str
    version: str
    digest: Digest
    sum: str
    go_mod_sum: str

    def to_go_sum_lines(self):
        return f"{self.path} {self.version} {self.sum}\n{self.path} {self.version}/go.mod {self.go_mod_sum}\n"


@rule
async def download_external_module(
    request: DownloadExternalModuleRequest,
) -> DownloadedExternalModule:
    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=EMPTY_DIGEST,
            command=("mod", "download", "-json", f"{request.path}@{request.version}"),
            description=f"Download external Go module at {request.path}@{request.version}.",
            output_directories=("gopath",),
        ),
    )

    # Decode the module metadata.
    metadata = json.loads(result.stdout)

    # Find the path within the digest where the source was downloaded. The path will have a sandbox-specific
    # prefix that we need to strip down to the `gopath` path component.
    absolute_source_path = metadata["Dir"]
    gopath_index = absolute_source_path.index("gopath/")
    source_path = absolute_source_path[gopath_index:]

    source_digest = await Get(
        Digest,
        DigestSubset(
            result.output_digest,
            PathGlobs(
                [f"{source_path}/**"],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"the DownloadExternalModuleRequest for {request.path}@{request.version}",
            ),
        ),
    )

    source_snapshot_stripped = await Get(Snapshot, RemovePrefix(source_digest, source_path))
    if "go.mod" not in source_snapshot_stripped.files:
        # There was no go.mod in the downloaded source. Use the generated go.mod from the go tooling which
        # was returned in the module metadata.
        go_mod_absolute_path = metadata.get("GoMod")
        if not go_mod_absolute_path:
            raise ValueError(
                f"No go.mod was provided in download of Go external module {request.path}@{request.version}, "
                "and the module metadata did not identify a generated go.mod file to use instead."
            )
        gopath_index = go_mod_absolute_path.index("gopath/")
        go_mod_path = go_mod_absolute_path[gopath_index:]
        go_mod_digest = await Get(
            Digest,
            DigestSubset(
                result.output_digest,
                PathGlobs(
                    [f"{go_mod_path}"],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin=f"the DownloadExternalModuleRequest for {request.path}@{request.version}",
                ),
            ),
        )
        go_mod_digest_stripped = await Get(
            Digest, RemovePrefix(go_mod_digest, os.path.dirname(go_mod_path))
        )

        # There should now be one file in the digest. Create a digest where that file is named go.mod
        # and then merge it into the sources.
        contents = await Get(DigestContents, Digest, go_mod_digest_stripped)
        assert len(contents) == 1
        go_mod_only_digest = await Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        path="go.mod",
                        content=contents[0].content,
                    )
                ]
            ),
        )
        source_digest_final = await Get(
            Digest, MergeDigests([go_mod_only_digest, source_snapshot_stripped.digest])
        )
    else:
        # If the module download has a go.mod, then just use the sources as is.
        source_digest_final = source_snapshot_stripped.digest

    return DownloadedExternalModule(
        path=request.path,
        version=request.version,
        digest=source_digest_final,
        sum=metadata["Sum"],
        go_mod_sum=metadata["GoModSum"],
    )


def rules():
    return collect_rules()
