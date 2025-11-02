# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pants.backend.docker.lint.hadolint.skip_field import SkipHadolintField
from pants.backend.docker.lint.hadolint.subsystem import Hadolint
from pants.backend.docker.subsystems.dockerfile_parser import (
    DockerfileInfo,
    DockerfileInfoRequest,
    parse_dockerfile,
)
from pants.backend.docker.target_types import DockerImageSourceField
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.external_tool import download_external_tool
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.fs import MergeDigests
from pants.engine.intrinsics import execute_process, merge_digests
from pants.engine.platform import Platform
from pants.engine.process import Process
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class HadolintFieldSet(FieldSet):
    required_fields = (DockerImageSourceField,)

    source: DockerImageSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipHadolintField).value


class HadolintRequest(LintTargetsRequest):
    field_set_type = HadolintFieldSet
    tool_subsystem = Hadolint  # type: ignore[assignment]
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


def generate_argv(
    dockerfile_infos: tuple[DockerfileInfo, ...], hadolint: Hadolint
) -> tuple[str, ...]:
    args = []
    if hadolint.config:
        args.append(f"--config={hadolint.config}")
    args.extend(hadolint.args)
    args.extend(info.source for info in dockerfile_infos)
    return tuple(args)


@rule(desc="Lint with Hadolint", level=LogLevel.DEBUG)
async def run_hadolint(
    request: HadolintRequest.Batch[HadolintFieldSet, Any],
    hadolint: Hadolint,
    platform: Platform,
) -> LintResult:
    downloaded_hadolint, config_files = await concurrently(
        download_external_tool(hadolint.get_request(platform)),
        find_config_file(hadolint.config_request()),
    )

    dockerfile_infos = await concurrently(
        parse_dockerfile(DockerfileInfoRequest(field_set.address), **implicitly())
        for field_set in request.elements
    )

    input_digest = await merge_digests(
        MergeDigests(
            (
                downloaded_hadolint.digest,
                config_files.snapshot.digest,
                *(info.digest for info in dockerfile_infos),
            )
        )
    )
    process_result = await execute_process(
        Process(
            argv=[downloaded_hadolint.exe, *generate_argv(dockerfile_infos, hadolint)],
            # Hadolint tries to read a configuration file from a few locations on the system:
            # https://github.com/hadolint/hadolint/blob/43d2bfe9f71dea9ddd203d5bdbd2cc1fb512e4dd/src/Hadolint/Config/Configfile.hs#L75-L101
            #
            # We don't want it to do this in order to have reproducible results machine to machine
            # and there is also the problem that on some machines, an unset (as opposed to empty)
            # HOME env var crashes hadolint with SIGSEGV.
            # See: https://github.com/hadolint/hadolint/issues/741
            #
            # As such, we set HOME to blank so no system configuration is found and, as a side
            # benefit, we don't crash.
            #
            # See https://github.com/pantsbuild/pants/issues/13735 for more details.
            env={"HOME": ""},
            input_digest=input_digest,
            description=f"Run `hadolint` on {pluralize(len(dockerfile_infos), 'Dockerfile')}.",
            level=LogLevel.DEBUG,
        ),
        **implicitly(),
    )

    return LintResult.create(request, process_result)


def rules():
    return [
        *collect_rules(),
        *HadolintRequest.rules(),
        UnionRule(ExportableTool, Hadolint),
    ]
