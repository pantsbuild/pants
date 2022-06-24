# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript, EntryPoint
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.option.option_types import IntOption, StrOption
from pants.util.docutil import git_url


class DebugPy(PythonToolBase):
    options_scope = "debugpy"
    help = "An implementation of the Debug Adapter Protocol for Python (https://github.com/microsoft/debugpy)."

    default_version = "debugpy==1.6.0"
    default_main = EntryPoint("debugpy")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<3.11"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "debugpy.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/debugpy.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    host = StrOption(
        "--host", default="127.0.0.1", help="The hostname to use when launching the debugpy server."
    )
    port = IntOption(
        "--port",
        default=5678,  # The canonical port
        help="The port to use when launching the debugpy server.",
    )

    def main_spec_args(self, value: EntryPoint | ConsoleScript) -> tuple[str, ...]:
        return (
            "-c",
            # NB: Use PEX itself to execute the value, since it already has code which can handle
            # the possible cases
            (
                "import os;"
                + "from pex.pex import PEX;"
                + "pex = PEX(pex=os.environ['PEX']);"
                + (
                    (
                        "from pex.dist_metadata import EntryPoint;"
                        + f"pex.execute_entry(EntryPoint.parse('run={value.spec}'));"
                    )
                    if isinstance(value, EntryPoint)
                    else f"pex.execute_script('{value.name}');"
                )
            ),
        )


class DebugPyLockfileSentinel(GenerateToolLockfileSentinel):
    resolve_name = DebugPy.options_scope


@rule
def setup_debugpy_lockfile(
    _: DebugPyLockfileSentinel, debugpy: DebugPy, python_setup: PythonSetup
) -> GeneratePythonLockfile:
    return GeneratePythonLockfile.from_tool(
        debugpy, use_pex=python_setup.generate_lockfiles_with_pex
    )


def rules():
    return (
        *collect_rules(),
        *lockfile.rules(),
        UnionRule(GenerateToolLockfileSentinel, DebugPyLockfileSentinel),
    )
