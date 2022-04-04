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
from pants.engine.fs import Digest, MergeDigests
from pants.engine.internals.native_engine import Snapshot
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


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
async def setup_isort(request: IsortRequest, isort: Isort) -> Process:
    isort_pex_get = Get(VenvPex, PexRequest, isort.to_pex_request())
    config_files_get = Get(
        ConfigFiles, ConfigFilesRequest, isort.config_request(request.snapshot.dirs)
    )
    isort_pex, config_files = await MultiGet(isort_pex_get, config_files_get)

    # Isort 5+ changes how config files are handled. Determine which semantics we should use.
    is_isort5 = False
    if isort.config:
        isort_info = await Get(PexResolveInfo, VenvPex, isort_pex)
        is_isort5 = any(
            dist_info.project_name == "isort" and dist_info.version.major >= 5
            for dist_info in isort_info
        )

    input_digest = await Get(
        Digest, MergeDigests((request.snapshot.digest, config_files.snapshot.digest))
    )

    process = await Get(
        Process,
        VenvPexProcess(
            isort_pex,
            argv=generate_argv(request.snapshot.files, isort, is_isort5=is_isort5),
            input_digest=input_digest,
            output_files=request.snapshot.files,
            description=f"Run isort on {pluralize(len(request.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return process


@rule(desc="Format with isort", level=LogLevel.DEBUG)
async def isort_fmt(request: IsortRequest, isort: Isort) -> FmtResult:
    if isort.skip:
        return FmtResult.skip(formatter_name=request.name)
    result = await Get(ProcessResult, IsortRequest, request)
    output_snapshot = await Get(Snapshot, Digest, result.output_digest)
    return FmtResult.create(request, result, output_snapshot, strip_chroot_path=True)


def rules():
    return [
        *collect_rules(),
        UnionRule(FmtRequest, IsortRequest),
        *pex.rules(),
    ]
