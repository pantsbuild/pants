# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import logging
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import ijson

from pants.backend.go.sdk import GoSdkProcess
from pants.backend.go.target_types import GoModuleSources
from pants.base.specs import AddressSpecs, AscendantAddresses, MaybeEmptySiblingAddresses
from pants.build_graph.address import Address
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
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
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import Target, UnexpandedTargets
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleDescriptor:
    import_path: str
    module_path: str
    module_version: str


# TODO: Add class docstring with info on the fields.
@dataclass(frozen=True)
class ResolvedGoModule:
    # The go_module target.
    target: Target

    # Import path of the Go module. Inferred from the import path in the go.mod file.
    import_path: str

    # Minimum Go version of the module from `go` statement in go.mod.
    minimum_go_version: Optional[str]

    # Metadata of referenced modules.
    modules: FrozenOrderedSet[ModuleDescriptor]

    # Digest containing go.mod and updated go.sum.
    digest: Digest


@dataclass(frozen=True)
class ResolveGoModuleRequest:
    address: Address


# Perform a minimal parsing of go.mod for the `module` and `go` directives. Full resolution of go.mod is left to
# the go toolchain. This could also probably be replaced by a go shim to make use of:
# https://pkg.go.dev/golang.org/x/mod/modfile
# TODO: Add full path to expections for applicable go.mod.
def basic_parse_go_mod(raw_text: bytes) -> Tuple[Optional[str], Optional[str]]:
    module_path = None
    minimum_go_version = None
    for line in raw_text.decode("utf-8").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            if parts[0] == "module":
                if module_path is not None:
                    raise ValueError("Multiple `module` directives found in go.mod file.")
                module_path = parts[1]
            elif parts[0] == "go":
                if minimum_go_version is not None:
                    raise ValueError("Multiple `go` directives found in go.mod file.")
                minimum_go_version = parts[1]
    return module_path, minimum_go_version


# Parse the output of `go mod download` into a list of module descriptors.
def parse_module_descriptors(raw_json: bytes) -> List[ModuleDescriptor]:
    # `ijson` cannot handle empty input so short-circuit if there is no data.
    if len(raw_json) == 0:
        return []

    module_descriptors = []
    for raw_module_descriptor in ijson.items(raw_json, "", multiple_values=True):
        module_descriptor = ModuleDescriptor(
            import_path=raw_module_descriptor["Path"],
            module_path=raw_module_descriptor["Path"],
            module_version=raw_module_descriptor["Version"],
        )
        module_descriptors.append(module_descriptor)
    return module_descriptors


@rule
async def resolve_go_module(
    request: ResolveGoModuleRequest,
) -> ResolvedGoModule:
    targets = await Get(UnexpandedTargets, Addresses([request.address]))
    if not targets:
        raise AssertionError(f"Address `{request.address}` did not resolve to any targets.")
    elif len(targets) > 1:
        raise AssertionError(f"Address `{request.address}` resolved to multiple targets.")
    target = targets[0]

    sources = await Get(SourceFiles, SourceFilesRequest([target.get(GoModuleSources)]))
    flattened_sources_snapshot = await Get(
        Snapshot, RemovePrefix(sources.snapshot.digest, request.address.spec_path)
    )

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=flattened_sources_snapshot.digest,
            command=("mod", "download", "-json", "all"),
            description="Resolve go_module metadata.",
            output_files=("go.mod", "go.sum"),
        ),
    )

    # Parse the go.mod for the module path and minimum Go version.
    module_path = None
    minimum_go_version = None
    digest_contents = await Get(DigestContents, Digest, flattened_sources_snapshot.digest)
    for entry in digest_contents:
        if entry.path == "go.mod":
            module_path, minimum_go_version = basic_parse_go_mod(entry.content)

    if module_path is None:
        raise ValueError("No `module` directive found in go.mod.")

    return ResolvedGoModule(
        target=target,
        import_path=module_path,
        minimum_go_version=minimum_go_version,
        modules=FrozenOrderedSet(parse_module_descriptors(result.stdout)),
        digest=result.output_digest,
    )


@dataclass(frozen=True)
class FindNearestGoModuleRequest:
    spec_path: str


@dataclass(frozen=True)
class ResolvedOwningGoModule:
    module_address: Optional[Address]


@rule
async def find_nearest_go_module(request: FindNearestGoModuleRequest) -> ResolvedOwningGoModule:
    # Obtain unexpanded targets and ensure file targets are filtered out. Unlike Python, file targets do not
    # make sense semantically for Go source since Go builds entire packages at a time. The filtering is
    # accomplished by requesting `UnexpandedTargets` and also filtering on `is_file_target`.
    spec_path = request.spec_path
    candidate_targets = await Get(
        UnexpandedTargets,
        AddressSpecs([AscendantAddresses(spec_path), MaybeEmptySiblingAddresses(spec_path)]),
    )
    go_module_targets = [
        tgt
        for tgt in candidate_targets
        if tgt.has_field(GoModuleSources) and not tgt.address.is_file_target
    ]

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


# TODO: Add integration tests for the `go-resolve` goal once we figure out its final form. For now, it is a debug
# tool to help update go.sum while developing the Go plugin and will probably change.
class GoResolveSubsystem(GoalSubsystem):
    name = "go-resolve"
    help = "Resolve a Go module's go.mod and update go.sum accordingly."


class GoResolveGoal(Goal):
    subsystem_cls = GoResolveSubsystem


@goal_rule
async def run_go_resolve(targets: UnexpandedTargets, workspace: Workspace) -> GoResolveGoal:
    # TODO: Use MultiGet to resolve the go_module targets.
    # TODO: Combine all of the go.sum's into a single Digest to write.
    for target in targets:
        if target.has_field(GoModuleSources) and not target.address.is_file_target:
            resolved_go_module = await Get(ResolvedGoModule, ResolveGoModuleRequest(target.address))
            # TODO: Only update the files if they actually changed.
            workspace.write_digest(resolved_go_module.digest, path_prefix=target.address.spec_path)
            logger.info(f"{target.address}: Updated go.mod and go.sum.\n")
        else:
            logger.info(f"{target.address}: Skipping because target is not a `go_module`.\n")
    return GoResolveGoal(exit_code=0)


@dataclass(frozen=True)
class DownloadExternalModuleRequest:
    path: str
    version: str


@dataclass(frozen=True)
class DownloadedExternalModule:
    path: str
    version: str
    digest: Digest


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
        path=request.path, version=request.version, digest=source_digest_final
    )


def rules():
    return collect_rules()
