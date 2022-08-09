# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    GeneratePythonToolLockfileSentinel,
)
from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import ConsoleScript, EntryPoint, MainSpecification
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
    default_interpreter_constraints = ["CPython>=3.7,<3.11"]

    register_lockfile = True
    default_lockfile_resource = ("pants.backend.python.subsystems", "debugpy.lock")
    default_lockfile_path = "src/python/pants/backend/python/subsystems/debugpy.lock"
    default_lockfile_url = git_url(default_lockfile_path)

    args = ArgsListOption(example="--log-to-stderr")

    @property
    def all_requirements(self) -> tuple[str, ...]:
        """All the raw requirement strings to install the tool.

        This may not include transitive dependencies: these are top-level requirements.
        """
        # NB: Locking with importlib_metadata is only necessary while debugpy supports Py 3.7, as
        # `importlib.metadata` was added in Py 3.8 and would allow us to resolve the console_script
        # using just the stdlib.
        #
        # Lastly, importlib_metadata, has so-far maintained a backwards-compatible API for
        # `entry_points`, so we lock using the lowest version but can be reasonably confident our
        # code will still work if executed in an environment with a user requirement on a newer
        # importlib_metadata.
        return (self.version, "importlib_metadata==1.4.0", *self.extra_requirements)

    @staticmethod
    def _get_main_spec_args(main: MainSpecification) -> tuple[str, ...]:
        if isinstance(main, EntryPoint):
            if main.function:
                return ("-c", f"import {main.module};{main.module}.{main.function}();")
            return ("-m", main.module)

        assert isinstance(main, ConsoleScript)
        return (
            "-c",
            (
                "import importlib_metadata;"
                + "eps = importlib_metadata.entry_points()['console_scripts'];"
                + f"ep = next(ep for ep in eps if ep.name == '{main.name}');"
                + "ep.load()()"
            ),
        )

    def get_args(
        self, debug_adapter: DebugAdapterSubsystem, main: MainSpecification
    ) -> tuple[str, ...]:
        return (
            "--listen",
            f"{debug_adapter.host}:{debug_adapter.port}",
            "--wait-for-client",
            *self.args,
            *self._get_main_spec_args(main),
        )


class DebugPyLockfileSentinel(GeneratePythonToolLockfileSentinel):
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
