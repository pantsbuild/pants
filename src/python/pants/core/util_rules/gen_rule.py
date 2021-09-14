# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import shlex
from typing import cast

from pants.core.target_types import GenRuleCommandField, GenRuleTarget
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    Process,
    ProcessResult,
    SearchPath,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import Sources
from pants.util.logging import LogLevel


@rule(desc="Running gen_rule", level=LogLevel.DEBUG)
async def run_gen_rule(gen_rule: GenRuleTarget) -> ProcessResult:
    args = shlex.split(cast(str, gen_rule[GenRuleCommandField].value))
    binary_request = BinaryPathRequest(
        binary_name=args[0],
        search_path=SearchPath(("/usr/bin", "/bin", "/usr/local/bin")),
    )
    paths, sources = await MultiGet(
        Get(BinaryPaths, BinaryPathRequest, binary_request),
        Get(
            SourceFiles,
            SourceFilesRequest(
                sources_fields=[gen_rule.get(Sources)],
                for_sources_types=(Sources,),
            ),
        ),
    )

    if not paths.first_path:
        raise BinaryNotFoundError(binary_request, rationale=f"execute gen_rule {gen_rule.address}")
    args[0] = paths.first_path.path

    return await Get(
        ProcessResult,
        Process(
            argv=tuple(args),
            description=f"Running gen_rule {gen_rule.address}",
            input_digest=sources.snapshot.digest,
            working_directory=gen_rule.address.spec_path,
        ),
    )


def rules():
    return collect_rules()
