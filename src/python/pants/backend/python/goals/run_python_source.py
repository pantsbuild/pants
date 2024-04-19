# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from typing import Optional

from pants.backend.python.goals.run_helper import (
    _create_python_source_run_dap_request,
    _create_python_source_run_request,
)
from pants.backend.python.subsystems.debugpy import DebugPy
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    Executable,
    InterpreterConstraintsField,
    PexEntryPointField,
    PythonRunGoalUseSandboxField,
    PythonSourceField,
)
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest
from pants.backend.python.util_rules.pex_environment import PexEnvironment, PexSubsystem
from pants.backend.python.util_rules.pex_from_targets import rules as pex_from_targets_rules
from pants.core.goals.run import (
    RunDebugAdapterRequest,
    RunFieldSet,
    RunInSandboxBehavior,
    RunInSandboxRequest,
    RunRequest,
)
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PythonSourceFieldSet(RunFieldSet):
    supports_debug_adapter = True
    required_fields = (PythonSourceField, PythonRunGoalUseSandboxField)
    run_in_sandbox_behavior = RunInSandboxBehavior.CUSTOM

    source: PythonSourceField
    interpreter_constraints: InterpreterConstraintsField
    _run_goal_use_sandbox: PythonRunGoalUseSandboxField

    def should_use_sandbox(self, python_setup: PythonSetup) -> bool:
        if self._run_goal_use_sandbox.value is None:
            return python_setup.default_run_goal_use_sandbox
        return self._run_goal_use_sandbox.value

    def _executable_main(self) -> Optional[Executable]:
        source = PurePath(self.source.value)
        source_name = source.stem if source.suffix == ".py" else source.name
        if not all(part.isidentifier() for part in source_name.split(".")):
            # If the python source is not importable (python modules can't be named with '-'),
            # then it must be an executable script.
            executable = Executable.create(self.address, self.source.value)
        else:
            # The module is importable, so entry_point will do the heavy lifting instead.
            executable = None
        return executable


@rule(level=LogLevel.DEBUG)
async def create_python_source_run_request(
    field_set: PythonSourceFieldSet,
    pex_env: PexEnvironment,
    python_setup: PythonSetup,
    pex_subsystem: PexSubsystem,
) -> RunRequest:
    return await _create_python_source_run_request(
        field_set.address,
        entry_point_field=PexEntryPointField(field_set.source.value, field_set.address),
        executable=field_set._executable_main(),
        pex_env=pex_env,
        pex_subsystem=pex_subsystem,
        run_in_sandbox=field_set.should_use_sandbox(python_setup),
    )


@rule(level=LogLevel.DEBUG)
async def create_python_source_run_in_sandbox_request(
    field_set: PythonSourceFieldSet, pex_env: PexEnvironment, python_setup: PythonSetup
) -> RunInSandboxRequest:
    # Unlike for `RunRequest`s, `run_in_sandbox` should _always_ be true when running in the
    # sandbox.
    run_request = await _create_python_source_run_request(
        field_set.address,
        entry_point_field=PexEntryPointField(field_set.source.value, field_set.address),
        executable=field_set._executable_main(),
        pex_env=pex_env,
        run_in_sandbox=True,
    )
    return run_request.to_run_in_sandbox_request()


@rule
async def create_python_source_debug_adapter_request(
    field_set: PythonSourceFieldSet,
    debugpy: DebugPy,
    debug_adapter: DebugAdapterSubsystem,
    pex_env: PexEnvironment,
    python_setup: PythonSetup,
) -> RunDebugAdapterRequest:
    debugpy_pex = await Get(
        # NB: We fold the debugpy PEX into the normally constructed VenvPex so that debugpy is in the
        # venv, but isn't the main entrypoint. Then we use PEX_* env vars to dynamically have debugpy
        # be invoked in that VenvPex. Hence, a vanilla Pex.
        Pex,
        PexRequest,
        debugpy.to_pex_request(
            interpreter_constraints=InterpreterConstraints.create_from_compatibility_fields(
                [field_set.interpreter_constraints], python_setup
            )
        ),
    )

    run_in_sandbox = field_set.should_use_sandbox(python_setup)
    run_request = await _create_python_source_run_request(
        field_set.address,
        entry_point_field=PexEntryPointField(field_set.source.value, field_set.address),
        executable=field_set._executable_main(),
        pex_env=pex_env,
        pex_path=[debugpy_pex],
        run_in_sandbox=run_in_sandbox,
    )

    return await _create_python_source_run_dap_request(
        run_request,
        debugpy=debugpy,
        debug_adapter=debug_adapter,
        run_in_sandbox=run_in_sandbox,
    )


def rules():
    return [
        *collect_rules(),
        *PythonSourceFieldSet.rules(),
        *pex_from_targets_rules(),
        *python_target_types_rules(),
    ]
