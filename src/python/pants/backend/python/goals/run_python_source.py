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
    InterpreterConstraintsField,
    PexEntryPointField,
    PythonRunGoalUseSandboxField,
    PythonSourceField,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest
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
    interpreter_constraints: InterpreterConstraintsField
    _run_goal_use_sandbox: PythonRunGoalUseSandboxField

    def get_run_goal_use_sandbox(self, python_setup: PythonSetup) -> bool:
        if self._run_goal_use_sandbox is None:
            return python_setup.default_run_goal_use_sandbox
        return self._run_goal_use_sandbox


@rule(level=LogLevel.DEBUG)
async def create_python_source_run_request(
    field_set: PythonSourceFieldSet, pex_env: PexEnvironment, python_setup: PythonSetup
) -> RunRequest:
    return await _create_python_source_run_request(
        field_set.address,
        entry_point_field=PexEntryPointField(field_set.source.value, field_set.address),
        pex_env=pex_env,
        run_in_sandbox=field_set.get_run_goal_use_sandbox(python_setup),
    )


@rule
async def create_python_source_debug_adapter_request(
    field_set: PythonSourceFieldSet,
    debugpy: DebugPy,
    debug_adapter: DebugAdapterSubsystem,
    pex_env: PexEnvironment,
    python_setup: PythonSetup,
) -> RunDebugAdapterRequest:
    debugpy_pex = await Get(
        Pex,
        PexRequest,
        debugpy.to_pex_request(
            interpreter_constraints=InterpreterConstraints.create_from_compatibility_fields(
                [field_set.interpreter_constraints], python_setup
            )
        ),
    )

    run_request = await _create_python_source_run_request(
        field_set.address,
        entry_point_field=PexEntryPointField(field_set.source.value, field_set.address),
        pex_env=pex_env,
        pex_path=[debugpy_pex],
        run_in_sandbox=field_set.get_run_goal_use_sandbox(python_setup),
    )

    return await _create_python_source_run_dap_request(
        run_request,
        debugpy=debugpy,
        debug_adapter=debug_adapter,
    )


def rules():
    return [
        *collect_rules(),
        UnionRule(RunFieldSet, PythonSourceFieldSet),
    ]
