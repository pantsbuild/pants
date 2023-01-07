# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Tuple

from pants.backend.python.lint.pydocstyle.subsystem import Pydocstyle, PydocstyleFieldSet
from pants.backend.python.util_rules import pex
from pants.backend.python.util_rules.pex import PexRequest, VenvPex, VenvPexProcess
from pants.core.goals.lint import LintResult, LintTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


class PydocstyleRequest(LintTargetsRequest):
    field_set_type = PydocstyleFieldSet
    tool_subsystem = Pydocstyle
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


def generate_argv(source_files: SourceFiles, pydocstyle: Pydocstyle) -> Tuple[str, ...]:
    args = []
    if pydocstyle.config is not None:
        args.append(f"--config={pydocstyle.config}")
    args.extend(pydocstyle.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(desc="Lint with Pydocstyle", level=LogLevel.DEBUG)
async def pydocstyle_lint(
    request: PydocstyleRequest.Batch,
    pydocstyle: Pydocstyle,
) -> LintResult:
    pydocstyle_pex_get = Get(VenvPex, PexRequest, pydocstyle.to_pex_request())

    config_files_get = Get(ConfigFiles, ConfigFilesRequest, pydocstyle.config_request)
    source_files_get = Get(
        SourceFiles, SourceFilesRequest(field_set.source for field_set in request.elements)
    )

    pydocstyle_pex, config_files, source_files = await MultiGet(
        pydocstyle_pex_get, config_files_get, source_files_get
    )

    input_digest = await Get(
        Digest,
        MergeDigests((source_files.snapshot.digest, config_files.snapshot.digest)),
    )

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            pydocstyle_pex,
            argv=generate_argv(source_files, pydocstyle),
            input_digest=input_digest,
            description=f"Run Pydocstyle on {pluralize(len(request.elements), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return LintResult.create(request, result)


def rules():
    return [*collect_rules(), *PydocstyleRequest.rules(), *pex.rules()]
