# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path
import textwrap
from collections import defaultdict
from dataclasses import dataclass

from pants.backend.go.lint.golangci_lint.skip_field import SkipGolangciLintField
from pants.backend.go.lint.golangci_lint.subsystem import GolangciLint
from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.backend.go.target_types import GoPackageSourcesField
from pants.backend.go.util_rules.build_opts import (
    GoBuildOptionsFromTargetRequest,
    go_extract_build_options_from_target,
)
from pants.backend.go.util_rules.go_mod import (
    GoModInfoRequest,
    OwningGoModRequest,
    determine_go_mod_info,
    find_owning_go_mod,
)
from pants.backend.go.util_rules.goroot import GoRoot
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.partitions import Partition, PartitionerType, Partitions
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.core.util_rules.system_binaries import BashBinary
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, FileContent, MergeDigests
from pants.engine.internals.graph import transitive_targets as transitive_targets_get
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, execute_process, merge_digests
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import FieldSet, SourcesField, Target, TransitiveTargetsRequest
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GolangciLintPartitionMetadata:
    """Metadata for a golangci-lint partition, identifying the go.mod context."""

    go_mod_address: Address

    @property
    def description(self) -> str:
        return f"module {self.go_mod_address}"


@dataclass(frozen=True)
class GolangciLintFieldSet(FieldSet):
    required_fields = (GoPackageSourcesField,)

    sources: GoPackageSourcesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGolangciLintField).value


class GolangciLintRequest(LintTargetsRequest):
    field_set_type = GolangciLintFieldSet
    tool_subsystem = GolangciLint  # type: ignore[assignment]
    partitioner_type = PartitionerType.CUSTOM


@rule(desc="Partition golangci-lint by go.mod", level=LogLevel.DEBUG)
async def partition_golangci_lint(
    request: GolangciLintRequest.PartitionRequest[GolangciLintFieldSet],
    golangci_lint: GolangciLint,
) -> Partitions[GolangciLintFieldSet, GolangciLintPartitionMetadata]:
    if golangci_lint.skip:
        return Partitions()

    # Find the owning go.mod for each field set
    owning_go_mods = await concurrently(
        find_owning_go_mod(OwningGoModRequest(fs.address), **implicitly())
        for fs in request.field_sets
    )

    # Group field sets by their owning go.mod
    by_go_mod: dict[Address, list[GolangciLintFieldSet]] = defaultdict(list)
    for field_set, owning in zip(request.field_sets, owning_go_mods):
        by_go_mod[owning.address].append(field_set)

    return Partitions(
        Partition(tuple(field_sets), GolangciLintPartitionMetadata(go_mod_addr))
        for go_mod_addr, field_sets in by_go_mod.items()
    )


@rule(desc="Lint with golangci-lint", level=LogLevel.DEBUG)
async def run_golangci_lint(
    request: GolangciLintRequest.Batch[GolangciLintFieldSet, GolangciLintPartitionMetadata],
    golangci_lint: GolangciLint,
    goroot: GoRoot,
    bash: BashBinary,
    platform: Platform,
    golang_subsystem: GolangSubsystem,
    golang_env_aware: GolangSubsystem.EnvironmentAware,
) -> LintResult:
    # Get the single go.mod address for this partition
    go_mod_address = request.partition_metadata.go_mod_address
    go_mod_dir = os.path.normpath(go_mod_address.spec_path) if go_mod_address.spec_path else ""

    transitive_targets = await transitive_targets_get(
        TransitiveTargetsRequest(field_set.address for field_set in request.elements),
        **implicitly(),
    )
    all_source_files_request = determine_source_files(
        SourceFilesRequest(
            tgt[SourcesField] for tgt in transitive_targets.closure if tgt.has_field(SourcesField)
        )
    )
    target_source_files_request = determine_source_files(
        SourceFilesRequest(field_set.sources for field_set in request.elements)
    )
    downloaded_golangci_lint_request = download_external_tool(golangci_lint.get_request(platform))
    config_files_request = find_config_file(golangci_lint.config_request())
    go_mod_info_request = determine_go_mod_info(GoModInfoRequest(go_mod_address))
    go_build_opts_request = go_extract_build_options_from_target(
        GoBuildOptionsFromTargetRequest(go_mod_address), **implicitly()
    )

    (
        target_source_files,
        all_source_files,
        downloaded_golangci_lint,
        config_files,
        go_mod_info,
        go_build_opts,
    ) = await concurrently(
        target_source_files_request,
        all_source_files_request,
        downloaded_golangci_lint_request,
        config_files_request,
        go_mod_info_request,
        go_build_opts_request,
    )

    cgo_enabled = go_build_opts.cgo_enabled

    # If cgo is enabled, golangci-lint needs to be able to locate the
    # associated tools in its environment. This is injected in $PATH in the
    # wrapper script.
    tool_search_path = ":".join(
        ["${GOROOT}/bin", *(golang_env_aware.cgo_tool_search_paths if cgo_enabled else ())]
    )

    # Compute package directories relative to the go.mod directory
    package_dirs = sorted(
        {
            os.path.relpath(os.path.dirname(f), go_mod_dir) if go_mod_dir else os.path.dirname(f)
            for f in target_source_files.snapshot.files
        }
    )

    # Compute path prefix to access sandbox root from working_directory
    # e.g., if working_directory is "foo/bar", prefix is "../../"
    sandbox_root_prefix = ""
    if go_mod_dir:
        depth = len(go_mod_dir.split(os.sep))
        sandbox_root_prefix = "../" * depth

    # golangci-lint requires an absolute path to a cache
    golangci_lint_run_script = FileContent(
        "__run_golangci_lint.sh",
        textwrap.dedent(
            f"""\
            export GOROOT={goroot.path}
            sandbox_root="$(/bin/pwd)"
            export PATH="{tool_search_path}"
            export GOPATH="${{sandbox_root}}/gopath"
            export GOCACHE="${{sandbox_root}}/gocache"
            export GOLANGCI_LINT_CACHE="$GOCACHE"
            export CGO_ENABLED={1 if cgo_enabled else 0}
            /bin/mkdir -p "$GOPATH" "$GOCACHE"
            exec "$@"
            """
        ).encode("utf-8"),
    )

    golangci_lint_run_script_digest = await create_digest(CreateDigest([golangci_lint_run_script]))
    input_digest = await merge_digests(
        MergeDigests(
            [
                golangci_lint_run_script_digest,
                downloaded_golangci_lint.digest,
                config_files.snapshot.digest,
                target_source_files.snapshot.digest,
                all_source_files.snapshot.digest,
                go_mod_info.digest,
            ]
        )
    )

    # Adjust paths to be relative to working_directory
    script_path = f"{sandbox_root_prefix}{golangci_lint_run_script.path}"
    exe_path = f"{sandbox_root_prefix}{downloaded_golangci_lint.exe}"

    argv: list[str] = [
        bash.path,
        script_path,
        exe_path,
        "run",
        # keep golangci-lint from complaining
        # about concurrent runs
        "--allow-parallel-runners",
    ]
    if golangci_lint.config:
        config_path = f"{sandbox_root_prefix}{golangci_lint.config}"
        argv.append(f"--config={config_path}")
    elif config_files.snapshot.files:
        config_path = f"{sandbox_root_prefix}{config_files.snapshot.files[0]}"
        argv.append(f"--config={config_path}")
    else:
        argv.append("--no-config")
    argv.extend(golangci_lint.args)
    # Add package paths relative to the module root
    argv.extend(f"./{p}" if p != "." else "./..." for p in package_dirs)

    process_result = await execute_process(
        Process(
            argv=argv,
            input_digest=input_digest,
            description=f"Run `golangci-lint` on {request.partition_metadata.description}.",
            level=LogLevel.DEBUG,
            working_directory=go_mod_dir or None,
        ),
        **implicitly(),
    )
    return LintResult.create(request, process_result)


def rules():
    return (
        *collect_rules(),
        *GolangciLintRequest.rules(),
        UnionRule(ExportableTool, GolangciLint),
    )
