# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap
from dataclasses import dataclass
from typing import List, Tuple, Optional

import ijson

from pants.backend.go.distribution import GoLangDistribution
from pants.backend.go.target_types import GoModule, GoModuleSources
from pants.build_graph.address import Address
from pants.core.util_rules.external_tool import DownloadedExternalTool, ExternalToolRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.stripped_source_files import StrippedSourceFiles
from pants.engine.console import Console
from pants.engine.fs import EMPTY_DIGEST, Digest, MergeDigests, RemovePrefix, Snapshot, CreateDigest, FileContent, \
    Workspace, DigestContents
from pants.engine.goal import GoalSubsystem, Goal
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessResult, BashBinary
from pants.engine.rules import rule, collect_rules, goal_rule
from pants.engine.target import WrappedTarget, Targets
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
# the go toolchain.
def basic_parse_go_mod(raw_text: bytes) -> Tuple[str, str]:
    module_path = None
    minimum_go_version = None
    for line in raw_text.decode("utf-8").splitlines():
        parts = line.strip().split()
        if parts[0] == "module":
            if module_path is not None:
                raise ValueError("Multiple `module` directives found in go.mod file.")
            module_path = parts[1]
        elif parts[0] == "go":
            if minimum_go_version is not None:
                raise ValueError("Multiple `go` directives found in go.mod file.")
            minimum_go_version = parts[1]
    return (module_path, minimum_go_version)


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
    request: ResolveGoModuleRequest, goroot: GoLangDistribution, platform: Platform, bash: BashBinary,
) -> ResolvedGoModule:
    downloaded_goroot = await Get(
        DownloadedExternalTool,
        ExternalToolRequest,
        goroot.get_request(platform),
    )

    wrapped_target = await Get(WrappedTarget, Address, request.address)
    target = wrapped_target.target

    sources = await Get(
        SourceFiles, SourceFilesRequest([target.get(GoModuleSources)])
    )
    flattened_sources_digest = await Get(Digest, RemovePrefix(sources.snapshot.digest, request.address.spec_path))
    flattened_sources_snapshot = await Get(Snapshot, Digest, flattened_sources_digest)
    if (
        len(flattened_sources_snapshot.files) != 2
        or "go.mod" not in flattened_sources_snapshot.files
        or "go.sum" not in flattened_sources_snapshot.files
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
        Digest, MergeDigests([flattened_sources_digest, downloaded_goroot.digest, analyze_script_digest])
    )

    process = Process(
        argv=[bash.path, "./analyze.sh"],
        input_digest=input_root_digest,
        description="Resolve go_module metadata.",
        output_files=["go.mod", "go.sum"],
        level=LogLevel.DEBUG,
    )

    result = await Get(ProcessResult, Process, process)

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


class GoResolveSubsystem(GoalSubsystem):
    name = "go-resolve"
    help = "Resolve Go go.mod and update go.sum accordingly. "


class GoResolveGoal(Goal):
    subsystem_cls = GoResolveSubsystem


@goal_rule
async def run_go_resolve(targets: Targets, console: Console,     workspace: Workspace,) -> GoResolveGoal:
    workspace.write_digest()



def rules():
    return collect_rules()
