# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.subsystems.debugpy import DebugPy
from pants.backend.python.target_types import PexBinaryDefaults, PexLayout
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunDebugAdapterRequest, RunFieldSet, RunRequest
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@rule(level=LogLevel.DEBUG)
async def create_pex_binary_run_request(
    field_set: PexBinaryFieldSet,
    pex_binary_defaults: PexBinaryDefaults,
    pex_env: PexEnvironment,
) -> RunRequest:
    built_pex = await Get(BuiltPackage, PexBinaryFieldSet, field_set)
    relpath = built_pex.artifacts[0].relpath
    assert relpath is not None
    if field_set.layout.value != PexLayout.ZIPAPP.value:
        relpath = os.path.join(relpath, "__main__.py")

    return RunRequest(
        digest=built_pex.digest,
        args=[os.path.join("{chroot}", relpath)],
    )


@rule
async def run_pex_debug_adapter_binary(
    field_set: PexBinaryFieldSet,
    debugpy: DebugPy,
    debug_adapter: DebugAdapterSubsystem,
) -> RunDebugAdapterRequest:
    # NB: Technically we could run this using `debugpy`, however it is unclear how the user
    # would be able to debug the code, as the client and server will disagree on the code's path.
    raise NotImplementedError(
        "Debugging a `pex_binary` using a debug adapter has not yet been implemented."
    )


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, PexBinaryFieldSet)]
