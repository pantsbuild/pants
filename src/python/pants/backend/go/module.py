# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap
from dataclasses import dataclass
from typing import List, Optional, Tuple

import ijson  # type: ignore

from pants.backend.go.distribution import GoLangDistribution
from pants.backend.go.target_types import GoModuleSources
from pants.build_graph.address import Address
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    MergeDigests,
    RemovePrefix,
    Snapshot,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import BashBinary, Process, ProcessResult
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import UnexpandedTargets
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class ModuleDescriptor:
    import_path: str
    module_path: str
    module_version: str


@dataclass(frozen=True)
class ResolvedGoModule:
    import_path: str
    minimum_go_version: Optional[str]
    modules: FrozenOrderedSet[ModuleDescriptor]
    digest: Digest


@dataclass(frozen=True)
class ResolveGoModuleRequest:
    address: Address


# Perform a minimal parsing of go.mod for the `module` and `go` directives. Full resolution of go.mod is left to
# the go toolchain. This could also probably be replaced by a go shim to make use of:
# https://pkg.go.dev/golang.org/x/mod/modfile
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
    goroot: GoLangDistribution,
    platform: Platform,
    bash: BashBinary,
) -> ResolvedGoModule:
    downloaded_goroot = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        goroot.get_request(platform),
    )

    targets = await Get(UnexpandedTargets, Addresses([request.address]))
    if not targets:
        raise ValueError(f"Address `{request.address}` did not resolve to any targets.")
    elif len(targets) > 1:
        raise ValueError(f"Address `{request.address}` resolved to multiple targets.")
    target = targets[0]

    sources = await Get(SourceFiles, SourceFilesRequest([target.get(GoModuleSources)]))
    flattened_sources_digest = await Get(
        Digest, RemovePrefix(sources.snapshot.digest, request.address.spec_path)
    )
    flattened_sources_snapshot = await Get(Snapshot, Digest, flattened_sources_digest)
    if (
        len(flattened_sources_snapshot.files) not in (1, 2)
        or "go.mod" not in flattened_sources_snapshot.files
    ):
        raise ValueError(f"Incomplete go_module sources: files={flattened_sources_snapshot.files}")

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
                exec ./go/bin/go mod download -json all
                """
                    ).encode("utf-8"),
                )
            ]
        ),
    )

    input_root_digest = await Get(
        Digest,
        MergeDigests([flattened_sources_digest, downloaded_goroot.digest, analyze_script_digest]),
    )

    process = Process(
        argv=[bash.path, "./analyze.sh"],
        input_digest=input_root_digest,
        description="Resolve go_module metadata.",
        output_files=["go.mod", "go.sum"],
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)

    # Parse the go.mod for the module path and minimum Go version.
    module_path = None
    minimum_go_version = None
    digest_contents = await Get(DigestContents, Digest, flattened_sources_digest)
    for entry in digest_contents:
        if entry.path == "go.mod":
            module_path, minimum_go_version = basic_parse_go_mod(entry.content)

    if module_path is None:
        raise ValueError("No `module` directive found in go.mod.")

    return ResolvedGoModule(
        import_path=module_path,
        minimum_go_version=minimum_go_version,
        modules=FrozenOrderedSet(parse_module_descriptors(result.stdout)),
        digest=result.output_digest,
    )


# TODO: Add integration tests for the `go-resolve` goal once we figure out its final form. For now, it is a debug
# tool to help update go.sum while developing the Go plugin and will probably change.
class GoResolveSubsystem(GoalSubsystem):
    name = "go-resolve"
    help = "Resolve a Go module's go.mod and update go.sum accordingly."


class GoResolveGoal(Goal):
    subsystem_cls = GoResolveSubsystem


@goal_rule
async def run_go_resolve(
    targets: UnexpandedTargets, console: Console, workspace: Workspace
) -> GoResolveGoal:
    for target in targets:
        if target.has_field(GoModuleSources) and not target.address.is_file_target:
            resolved_go_module = await Get(ResolvedGoModule, ResolveGoModuleRequest(target.address))
            # TODO: Only update the files if they actually changed.
            workspace.write_digest(resolved_go_module.digest, path_prefix=target.address.spec_path)
            console.write_stdout(f"{target.address}: Updated go.mod and go.sum.\n")
        else:
            console.write_stdout(
                f"{target.address}: Skipping because target is not a `go_module`.\n"
            )
    return GoResolveGoal(exit_code=0)


def rules():
    return collect_rules()
