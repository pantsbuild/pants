# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.target_types import EntryPoint
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import ArgsListOption
from pants.util.docutil import git_url


class DebugPy(PythonToolBase):
    options_scope = "debugpy"
    name = options_scope
    help = "An implementation of the Debug Adapter Protocol for Python (https://github.com/microsoft/debugpy)."

    default_version = "debugpy==1.6.0"
    default_main = EntryPoint("debugpy")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "debugpy.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/debugpy.lock"
    default_lockfile_url = git_url(default_lockfile_path)

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


class DebugPyLockfileSentinel(GeneratePythonToolLockfileSentinel):
    resolve_name = DebugPy.options_scope


@rule
def setup_debugpy_lockfile(_: DebugPyLockfileSentinel, debugpy: DebugPy) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(debugpy)


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, DebugPyLockfileSentinel),
    )
