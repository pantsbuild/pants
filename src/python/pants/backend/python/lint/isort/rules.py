# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.isort.skip_field import SkipIsortField
from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.target_types import PythonSourceField
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, PexResolveInfo, VenvPex, VenvPexProcess
from pants.core.goals.fmt import FmtRequest, FmtResult
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize, strip_v2_chroot_path


@dataclass(frozen=True)
class IsortFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    source: PythonSourceField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipIsortField).value


class IsortRequest(FmtRequest):
    field_set_type = IsortFieldSet
    name = Isort.options_scope


@dataclass(frozen=True)
class Setup:
    process: Process
    original_snapshot: Snapshot


def generate_argv(
    source_files: tuple[str, ...], isort: Isort, *, is_isort5: bool
) -> Tuple[str, ...]:
    args = [*isort.args]
    if is_isort5 and len(isort.config) == 1:
        explicitly_configured_config_args = [
            arg
            for arg in isort.args
            if (
                arg.startswith("--sp")
                or arg.startswith("--settings-path")
                or arg.startswith("--settings-file")
                or arg.startswith("--settings")
            )
        ]
        # TODO: Deprecate manually setting this option, but wait until we deprecate
        #  `[isort].config` to be a string rather than list[str] option.
        if not explicitly_configured_config_args:
            args.append(f"--settings={isort.config[0]}")
    args.extend(source_files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def setup_isort(request: IsortRequest, isort: Isort) -> Setup:
    isort_pex_get = Get(VenvPex, PexRequest, isort.to_pex_request())
    source_files_get = Get(
        SourceFiles,
        SourceFilesRequest(field_set.source for field_set in request.field_sets),
    )
    source_files, isort_pex = await MultiGet(source_files_get, isort_pex_get)

    source_files_snapshot = (
        source_files.snapshot
        if request.prior_formatter_result is None
        else request.prior_formatter_result
    )

    config_files = await Get(
        ConfigFiles, ConfigFilesRequest, isort.config_request(source_files_snapshot.dirs)
    )

    # Isort 5+ changes how config files are handled. Determine which semantics we should use.
    is_isort5 = False
    if isort.config:
        isort_info = await Get(PexResolveInfo, VenvPex, isort_pex)
        is_isort5 = any(
            dist_info.project_name == "isort" and dist_info.version.major >= 5
            for dist_info in isort_info
        )

    input_digest = await Get(
        Digest, MergeDigests((source_files_snapshot.digest, config_files.snapshot.digest))
    )

    process = await Get(
        Process,
        VenvPexProcess(
            isort_pex,
            argv=generate_argv(source_files_snapshot.files, isort, is_isort5=is_isort5),
            input_digest=input_digest,
            output_files=source_files_snapshot.files,
            description=f"Run isort on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return Setup(process, original_snapshot=source_files_snapshot)


@rule(desc="Format with isort", level=LogLevel.DEBUG)
async def isort_fmt(request: IsortRequest, isort: Isort) -> FmtResult:
    if isort.skip:
        return FmtResult.skip(formatter_name=request.name)
    setup = await Get(Setup, IsortRequest, request)
    result = await Get(ProcessResult, Process, setup.process)
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult(
        setup.original_snapshot,
        output_snapshot,
        stdout=strip_v2_chroot_path(result.stdout),
        stderr=strip_v2_chroot_path(result.stderr),
        formatter_name=request.name,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(FmtRequest, IsortRequest),
        *pex.rules(),
    ]
