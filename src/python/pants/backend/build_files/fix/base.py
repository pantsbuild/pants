# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable

from pants.backend.build_files.utils import _get_build_file_partitioner_rules
from pants.core.goals.fix import FixFilesRequest
from pants.core.util_rules.partitions import PartitionerType


class FixBuildFilesRequest(FixFilesRequest):
    partitioner_type = PartitionerType.CUSTOM

    @classmethod
    def _get_rules(cls) -> Iterable:
        assert cls.partitioner_type is PartitionerType.CUSTOM
        yield from _get_build_file_partitioner_rules(cls)
        yield from super()._get_rules()
