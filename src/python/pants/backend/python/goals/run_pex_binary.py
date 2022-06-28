# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.goals.run_helper import _create_python_source_run_request
from pants.backend.python.subsystems.debugpy import DebugPy
from pants.backend.python.target_types import (
    PexBinaryDefaults,
    ResolvePexEntryPointRequest,
    ResolvedPexEntryPoint,
)
from pants.backend.python.util_rules.pex import Pex, PexRequest
from pants.backend.python.util_rules.pex_environment import PexEnvironment, PexRuntimeEnvironment
from pants.core.goals.package import BuiltPackage
from pants.core.goals.run import RunDebugAdapterRequest, RunFieldSet, RunRequest
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


def _in_chroot(relpath: str) -> str:
    return os.path.join("{chroot}", relpath)


@rule(level=LogLevel.DEBUG)
async def create_pex_binary_run_request(
    field_set: PexBinaryFieldSet,
    pex: PexRuntimeEnvironment,
    pex_binary_defaults: PexBinaryDefaults,
    pex_env: PexEnvironment,
) -> RunRequest:
    if pex.run_packaged_firstparty:
        built_pex = await Get(BuiltPackage, PexBinaryFieldSet, field_set)
        relpath = built_pex.artifacts[0].relpath
        assert relpath is not None
        return RunRequest(
            digest=built_pex.digest,
            args=[os.path.join("{chroot}", relpath)],
        )

    return await _create_python_source_run_request(
        field_set.address,
        entry_point_field=field_set.entry_point,
        pex_env=pex_env,
        run_in_sandbox=False,
        console_script=field_set.script.value,
        additional_pex_args=field_set.generate_additional_args(pex_binary_defaults),
    )


@rule
async def run_pex_debug_adapter_binary(
    field_set: PexBinaryFieldSet,
    debugpy: DebugPy,
    debug_adapter: DebugAdapterSubsystem,
) -> RunDebugAdapterRequest:
    entry_point, regular_run_request, debugpy_pex = await MultiGet(
        Get(
            ResolvedPexEntryPoint,
            ResolvePexEntryPointRequest(field_set.entry_point),
        ),
        Get(RunRequest, PexBinaryFieldSet, field_set),
        Get(Pex, PexRequest, debugpy.to_pex_request()),
    )

    entry_point_or_script = entry_point.val or field_set.script.value
    assert entry_point_or_script is not None
    merged_digest = await Get(
        Digest, MergeDigests([regular_run_request.digest, debugpy_pex.digest])
    )
    extra_env = dict(regular_run_request.extra_env)
    extra_env["PEX_PATH"] = os.pathsep.join(
        [
            extra_env["PEX_PATH"],
            # For debugpy to work properly, we need to have just one "environment" for our
            # command to run in. Therefore, we cobble one together by exeucting debugpy's PEX, and
            # shoehorning in the original PEX through PEX_PATH.
            _in_chroot(os.path.basename(regular_run_request.args[1])),
        ]
    )
    args = [
        regular_run_request.args[0],  # python executable
        _in_chroot(debugpy_pex.name),
        *debugpy.get_args(debug_adapter, entry_point_or_script),
    ]

    return RunDebugAdapterRequest(digest=merged_digest, args=args, extra_env=extra_env)


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, PexBinaryFieldSet)]
