# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.adhoc import adhoc_tool, run_system_binary
from pants.backend.adhoc.target_types import AdhocToolTarget, SystemBinaryTarget
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.core.util_rules.adhoc_process_support import runnable


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


def build_file_aliases():
    return BuildFileAliases(
        objects={
            "_runnable": runnable,
        },
    )
