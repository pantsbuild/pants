# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.goals.package_pex_binary import PexBinaryFieldSet
from pants.backend.python.goals.run_helper import (
    _create_python_source_run_dap_request,
    _create_python_source_run_request,
)
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
    return await _create_python_source_run_request(
        field_set.address,
        entry_point_field=field_set.entry_point,
        pex_env=pex_env,
        run_in_sandbox=True,
        console_script=field_set.script.value,
        additional_pex_args=field_set.generate_additional_args(pex_binary_defaults),
    )


@rule
async def run_pex_debug_adapter_binary(
    field_set: PexBinaryFieldSet,
    debugpy: DebugPy,
    debug_adapter: DebugAdapterSubsystem,
) -> RunDebugAdapterRequest:
    run_request = await Get(RunRequest, PexBinaryFieldSet, field_set)
    return await _create_python_source_run_dap_request(
        run_request,
        entry_point_field=field_set.entry_point,
        debugpy=debugpy,
        debug_adapter=debug_adapter,
        console_script=field_set.script.value,
    )


def rules():
    return [*collect_rules(), UnionRule(RunFieldSet, PexBinaryFieldSet)]
