# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.adhoc import adhoc_tool, run_system_binary
from pants.backend.adhoc.target_types import AdhocToolTarget, SystemBinaryTarget


def target_types():
    return [
        AdhocToolTarget,
        SystemBinaryTarget,
    ]


def rules():
    return [
        *adhoc_tool.rules(),
        *run_system_binary.rules(),
    ]
