# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from typing import Iterable

from pants.backend.cc.goals.package import CCBinaryFieldSet
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.core.goals.run import RunDebugAdapterRequest, RunFieldSet, RunRequest
from pants.engine.internals.selectors import Get
from pants.engine.rules import Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@rule(level=LogLevel.DEBUG)
async def run_cc_binary(field_set: CCBinaryFieldSet) -> RunRequest:
    """Run a C/C++ binary.

    This will first run the `package` goal to create a binary, then run it.
    """
    binary = await Get(BuiltPackage, PackageFieldSet, field_set)
    artifact_relpath = binary.artifacts[0].relpath
    assert artifact_relpath is not None
    return RunRequest(digest=binary.digest, args=(os.path.join("{chroot}", artifact_relpath),))


@rule(level=LogLevel.DEBUG)
async def cc_binary_run_debug_adapter_request(
    field_set: CCBinaryFieldSet,
) -> RunDebugAdapterRequest:
    raise NotImplementedError(
        "Debugging a CC binary using a debug adapter has not yet been implemented."
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(RunFieldSet, CCBinaryFieldSet),
    )
