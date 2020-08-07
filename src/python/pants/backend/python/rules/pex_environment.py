# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Tuple

from pants.backend.python.subsystems import subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEnvironment
from pants.engine import process
from pants.engine.engine_aware import EngineAware
from pants.engine.process import BinaryPathRequest, BinaryPaths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.option.subsystem import Subsystem
from pants.python.python_setup import PythonSetup
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import create_path_env_var


class PexRuntimeEnvironment(Subsystem):
    """How Pants uses Pex to run Python subprocesses."""

    options_scope = "pex"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        # TODO(#9760): We'll want to deprecate this in favor of a global option which allows for a
        #  per-process override.
        register(
            "--executable-search-paths",
            advanced=True,
            type=list,
            default=["<PATH>"],
            metavar="<binary-paths>",
            help=(
                "The PATH value that will be used by the PEX subprocess and any subprocesses it "
                'spawns. The special string "<PATH>" will expand to the contents of the PATH env '
                "var."
            ),
        )
        register(
            "--bootstrap-interpreter-names",
            advanced=True,
            type=list,
            default=["python", "python3", "python2"],
            metavar="<bootstrap-python-names>",
            help=(
                "The names of Python binaries to search for to bootstrap PEX files with. This does "
                "not impact which Python interpreter is used to run your code, only what is used "
                "to run the PEX tool. See the `interpreter_search_paths` option in "
                "`[python-setup]` to influence where interpreters are searched for."
            ),
        )

    @memoized_property
    def path(self) -> Tuple[str, ...]:
        def iter_path_entries():
            for entry in self.options.executable_search_paths:
                if entry == "<PATH>":
                    path = os.environ.get("PATH")
                    if path:
                        for path_entry in path.split(os.pathsep):
                            yield path_entry
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))

    @property
    def bootstrap_interpreter_names(self) -> Tuple[str, ...]:
        return tuple(self.options.bootstrap_interpreter_names)


@dataclass(frozen=True)
class PexEnvironment(EngineAware):
    path: Tuple[str, ...]
    interpreter_search_paths: Tuple[str, ...]
    subprocess_environment_dict: FrozenDict[str, str]
    bootstrap_python: Optional[str] = None

    def create_argv(
        self, pex_path: str, *args: str, always_use_shebang: bool = False
    ) -> Iterable[str]:
        argv = [self.bootstrap_python] if self.bootstrap_python and not always_use_shebang else []
        argv.extend((pex_path, *args))
        return argv

    @property
    def environment_dict(self) -> Mapping[str, str]:
        return dict(
            PATH=create_path_env_var(self.path),
            PEX_PYTHON_PATH=create_path_env_var(self.interpreter_search_paths),
            PEX_INHERIT_PATH="false",
            PEX_IGNORE_RCFILES="true",
            **self.subprocess_environment_dict,
        )

    def level(self) -> LogLevel:
        return LogLevel.DEBUG if self.bootstrap_python else LogLevel.WARN

    def message(self) -> str:
        if not self.bootstrap_python:
            return (
                "No bootstrap Python executable could be found from the option "
                "`interpreter_search_paths` in the `[python-setup]` scope. Will attempt to run "
                "PEXes directly."
            )
        return f"Selected {self.bootstrap_python} to bootstrap PEXes with."


@rule(desc="Find PEX Python")
async def find_pex_python(
    python_setup: PythonSetup,
    pex_runtime_environment: PexRuntimeEnvironment,
    subprocess_environment: SubprocessEnvironment,
) -> PexEnvironment:
    # PEX files are compatible with bootstrapping via python2.7 or python 3.5+. The bootstrap
    # code will then re-exec itself if the underlying PEX user code needs a more specific python
    # interpreter. As such, we look for many Pythons usable by the PEX bootstrap code here for
    # maximum flexibility.
    all_python_binary_paths = await MultiGet(
        [
            Get(
                BinaryPaths,
                BinaryPathRequest(
                    search_path=python_setup.interpreter_search_paths, binary_name=binary_name
                ),
            )
            for binary_name in pex_runtime_environment.bootstrap_interpreter_names
        ]
    )

    def first_python_binary() -> Optional[str]:
        for binary_paths in all_python_binary_paths:
            if binary_paths.first_path:
                return binary_paths.first_path
        return None

    return PexEnvironment(
        path=pex_runtime_environment.path,
        interpreter_search_paths=tuple(python_setup.interpreter_search_paths),
        subprocess_environment_dict=FrozenDict(subprocess_environment.environment_dict),
        bootstrap_python=first_python_binary(),
    )


def rules():
    return [*collect_rules(), *process.rules(), *subprocess_environment.rules()]
