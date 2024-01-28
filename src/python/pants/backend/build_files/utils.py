# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable

from pants.core.goals.fix import FixFilesRequest
from pants.core.goals.multi_tool_goal_helper import SkippableSubsystem
from pants.core.util_rules.partitions import Partitions
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.native_engine import FilespecMatcher
from pants.engine.rules import collect_rules, rule
from pants.util.memo import memoized


@memoized
def _get_build_file_partitioner_rules(cls) -> Iterable:
    """Returns the BUILD file partitioner rule."""

    @rule(
        canonical_name_suffix=cls.__name__,
        _param_type_overrides={
            "request": cls.PartitionRequest,
            "subsystem": cls.tool_subsystem,
        },
    )
    async def partition_build_files(
        request: FixFilesRequest.PartitionRequest,
        subsystem: SkippableSubsystem,
        build_file_options: BuildFileOptions,
    ) -> Partitions:
        if subsystem.skip:
            return Partitions()

        specified_build_files = FilespecMatcher(
            includes=[os.path.join("**", p) for p in build_file_options.patterns],
            excludes=build_file_options.ignores,
        ).matches(request.files)

        return Partitions.single_partition(specified_build_files)

    return collect_rules(locals())
