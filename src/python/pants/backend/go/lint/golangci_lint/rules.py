# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from dataclasses import dataclass
from typing import Any, cast

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
from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.core.util_rules.system_binaries import BashBinary
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
class GolangciLintFieldSet(FieldSet):
    required_fields = (GoPackageSourcesField,)

    sources: GoPackageSourcesField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipGolangciLintField).value


class GolangciLintRequest(LintTargetsRequest):
    field_set_type = GolangciLintFieldSet
    tool_subsystem = cast(type[SkippableSubsystem], GolangciLint)
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(desc="Lint with golangci-lint", level=LogLevel.DEBUG)
async def run_golangci_lint(
    request: GolangciLintRequest.Batch[GolangciLintFieldSet, Any],
    golangci_lint: GolangciLint,
    goroot: GoRoot,
    bash: BashBinary,
    platform: Platform,
    golang_subsystem: GolangSubsystem,
    golang_env_aware: GolangSubsystem.EnvironmentAware,
) -> LintResult:
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

    (
        target_source_files,
        all_source_files,
        downloaded_golangci_lint,
        config_files,
    ) = await concurrently(
        target_source_files_request,
        all_source_files_request,
        downloaded_golangci_lint_request,
        config_files_request,
    )

    owning_go_mods = await concurrently(
        find_owning_go_mod(OwningGoModRequest(field_set.address), **implicitly())
        for field_set in request.elements
    )
    owning_go_mod_addresses = {x.address for x in owning_go_mods}
    go_mod_infos = await concurrently(
        determine_go_mod_info(GoModInfoRequest(address)) for address in owning_go_mod_addresses
    )
    go_build_opts = await concurrently(
        go_extract_build_options_from_target(
            GoBuildOptionsFromTargetRequest(address), **implicitly()
        )
        for address in owning_go_mod_addresses
    )

    cgo_enabled = any(build_opts.cgo_enabled for build_opts in go_build_opts)

    # If cgo is enabled, golangci-lint needs to be able to locate the
    # associated tools in its environment. This is injected in $PATH in the
    # wrapper script.
    tool_search_path = ":".join(
        ["${GOROOT}/bin", *(golang_env_aware.cgo_tool_search_paths if cgo_enabled else ())]
    )

    # golangci-lint requires a absolute path to a cache
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
                *(info.digest for info in set(go_mod_infos)),
            ]
        )
    )

    argv: list[str] = [
        bash.path,
        golangci_lint_run_script.path,
        downloaded_golangci_lint.exe,
        "run",
        # keep golangci-lint from complaining
        # about concurrent runs
        "--allow-parallel-runners",
    ]
    if golangci_lint.config:
        argv.append(f"--config={golangci_lint.config}")
    elif config_files.snapshot.files:
        argv.append(f"--config={config_files.snapshot.files[0]}")
    else:
        argv.append("--no-config")
    argv.extend(golangci_lint.args)

    process_result = await execute_process(
        Process(
            argv=argv,
            input_digest=input_digest,
            description="Run `golangci-lint`.",
            level=LogLevel.DEBUG,
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
