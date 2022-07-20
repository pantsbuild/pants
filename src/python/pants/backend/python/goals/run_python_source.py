# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.python.goals.run_helper import (
    _create_python_source_run_dap_request,
    _create_python_source_run_request,
)
from pants.backend.python.subsystems.debugpy import DebugPy
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    PexEntryPointField,
    PythonRunGoalUseSandboxField,
    PythonSourceField,
)
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.core.goals.run import RunDebugAdapterRequest, RunFieldSet, RunRequest
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonSourceFieldSet(RunFieldSet):
    required_fields = (PythonSourceField, PythonRunGoalUseSandboxField)

    source: PythonSourceField
    run_goal_use_sandbox: PythonRunGoalUseSandboxField


@rule(level=LogLevel.DEBUG)
async def create_python_source_run_request(
    field_set: PythonSourceFieldSet, pex_env: PexEnvironment, python: PythonSetup
) -> RunRequest:
    run_goal_use_sandbox = field_set.run_goal_use_sandbox.value
    if run_goal_use_sandbox is None:
        run_goal_use_sandbox = python.default_run_goal_use_sandbox

    return await _create_python_source_run_request(
        field_set.address,
        entry_point_field=PexEntryPointField(field_set.source.value, field_set.address),
        pex_env=pex_env,
        run_in_sandbox=run_goal_use_sandbox,
        # Setting --venv is kosher because the PEX we create is just for the thirdparty deps.
        additional_pex_args=["--venv"],
    )


@rule
async def create_python_source_debug_adapter_request(
    field_set: PythonSourceFieldSet,
    debugpy: DebugPy,
    debug_adapter: DebugAdapterSubsystem,
) -> RunDebugAdapterRequest:
    run_request = await Get(RunRequest, PythonSourceFieldSet, field_set)
    return await _create_python_source_run_dap_request(
        run_request,
        entry_point_field=PexEntryPointField(field_set.source.value, field_set.address),
        debugpy=debugpy,
        debug_adapter=debug_adapter,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(RunFieldSet, PythonSourceFieldSet),
    ]
