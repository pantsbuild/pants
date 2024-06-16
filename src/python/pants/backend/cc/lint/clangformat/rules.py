# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.backend.cc.lint.clangformat.subsystem import ClangFormat
from pants.backend.cc.target_types import CCSourceField
from pants.backend.python.util_rules.pex import Pex, PexProcess, PexRequest
from pants.core.goals.fmt import FmtResult, FmtTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import PartitionerType
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, concurrently, Rule, collect_rules, rule
from pants.backend.python.util_rules.pex import create_pex
from pants.core.util_rules.config_files import find_config_file
from pants.engine.intrinsics import merge_digests_request_to_digest
from pants.engine.rules import implicitly
from pants.engine.target import FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClangFormatFmtFieldSet(FieldSet):
    required_fields = (CCSourceField,)

    sources: CCSourceField


class ClangFormatRequest(FmtTargetsRequest):
    field_set_type = ClangFormatFmtFieldSet
    tool_subsystem = ClangFormat
    partitioner_type = PartitionerType.DEFAULT_SINGLE_PARTITION


@rule(level=LogLevel.DEBUG)
async def clangformat_fmt(request: ClangFormatRequest.Batch, clangformat: ClangFormat) -> FmtResult:
    # Look for any/all of the clang-format configuration files (recurse sub-dirs)
    config_files_get = find_config_file(**implicitly({clangformat.config_request(request.snapshot.dirs): ConfigFilesRequest}))

    clangformat_pex, config_files = await concurrently(
        create_pex(**implicitly({clangformat.to_pex_request(): PexRequest})),
    )

    # Merge source files, config files, and clang-format pex process
    input_digest = await merge_digests_request_to_digest(MergeDigests([request.snapshot.digest, config_files.snapshot.digest, clangformat_pex.digest]), **implicitly())

    result = await Get(
        ProcessResult,
        PexProcess(
            clangformat_pex,
            argv=(
                "--style=file",  # Look for .clang-format files
                "--fallback-style=webkit",  # Use WebKit if there is no config file
                "-i",  # In-place edits
                "--Werror",  # Formatting warnings as errors
                *clangformat.args,  # User-added arguments
                *request.files,
            ),
            input_digest=input_digest,
            output_files=request.files,
            description=f"Run clang-format on {pluralize(len(request.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return await FmtResult.create(request, result)


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *ClangFormatRequest.rules(),
    )
