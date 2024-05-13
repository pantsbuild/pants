# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import EntryPoint
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.engine.rules import collect_rules
from pants.option.option_types import ArgsListOption


class DebugPy(PythonToolBase):
    options_scope = "debugpy"
    name = options_scope
    help_short = "An implementation of the Debug Adapter Protocol for Python (https://github.com/microsoft/debugpy)."

    default_main = EntryPoint("debugpy")
    default_requirements = ["debugpy>=1.6.5,<1.7"]

    register_interpreter_constraints = True

    default_lockfile_resource = ("pants.backend.python.subsystems", "debugpy.lock")

    args = ArgsListOption(example="--log-to-stderr")

    # NB: The debugpy arguments assume that:
    #   1. debugpy is being invoked in a venv (likely we're in a VenvPex)
    #   2. debugpy is in the same venv as the user code
    def get_args(self, debug_adapter: DebugAdapterSubsystem) -> tuple[str, ...]:
        return (
            "--listen",
            f"{debug_adapter.host}:{debug_adapter.port}",
            "--wait-for-client",
            *self.args,
            "-c",
            "__import__('runpy').run_path(__import__('os').environ['VIRTUAL_ENV'] + '/pex', run_name='__main__')",
        )


def rules():
    return collect_rules()
