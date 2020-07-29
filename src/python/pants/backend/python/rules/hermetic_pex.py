# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Tuple

from pants.backend.python.subsystems.subprocess_environment import SubprocessEnvironment
from pants.engine import process
from pants.engine.engine_aware import EngineAware
from pants.engine.fs import Digest
from pants.engine.process import BinaryPathRequest, BinaryPaths, Process
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.option.subsystem import Subsystem
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import create_path_env_var


@dataclass(frozen=True)
class PexEnvironment(EngineAware):
    path: Iterable[str]
    interpreter_search_paths: Iterable[str]
    bootstrap_python: Optional[str] = None

    def create_argv(self, pex_path: str, *args: str) -> Iterable[str]:
        argv = [self.bootstrap_python] if self.bootstrap_python else []
        argv.extend((pex_path, *args))
        return argv

    @property
    def environment_dict(self) -> Mapping[str, str]:
        return dict(
            PATH=create_path_env_var(self.path),
            PEX_PYTHON_PATH=create_path_env_var(self.interpreter_search_paths),
        )

    def level(self) -> Optional[LogLevel]:
        return LogLevel.INFO if self.bootstrap_python else LogLevel.WARN

    def message(self) -> Optional[str]:
        if not self.bootstrap_python:
            return (
                "No bootstrap python executable could be found. "
                "Will attempt to run PEXes directly."
            )
        return f"Selected {self.bootstrap_python} to bootstrap PEXes with."


class PexRuntimeEnvironment(Subsystem):
    """How Pants uses Pex to run Python subprocesses."""

    options_scope = "pex"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--binary-search-path",
            advanced=True,
            type=list,
            default=["<PATH>"],
            metavar="<binary-paths>",
            help=(
                "A list of paths to search for binaries needed by PEX subprocess. The special "
                'string "<PATH>" will expand to the contents of the PATH env var.'
            ),
        )
        register(
            "--bootstrap-interpreter-names",
            advanced=True,
            type=list,
            default=["python", "python3", "python2"],
            metavar="<bootstrap-python-names>",
            help=(
                "The names of python binaries to search for to bootstrap PEX files with. Earlier "
                "names in the list will be preferred over later names and the first matching "
                "interpreter found will be used to execute the PEX bootstrap stage. If no matching "
                "interpreters are found, PEXes will be executed directly relying on their embedded "
                "shebang and the $PATH (see --binary-search-path) to locate a bootstrap "
                "interpreter."
            ),
        )

    @memoized_property
    def path(self) -> Tuple[str, ...]:
        def iter_path_entries():
            for entry in self.options.binary_search_path:
                if entry == "<PATH>":
                    # TODO(#9760): This is not very robust. We want to be able to read an env var
                    #  safely via the engine.
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


@rule(desc="Find PEX Python")
async def find_pex_python(
    python_setup: PythonSetup, pex_runtime_environment: PexRuntimeEnvironment
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
        interpreter_search_paths=python_setup.interpreter_search_paths,
        bootstrap_python=first_python_binary(),
    )


class HermeticPex:
    """A mixin for types that provide an executable Pex that should be executed hermetically."""

    def create_process(
        self,
        pex_environment: PexEnvironment,
        subprocess_environment: SubprocessEnvironment,
        *,
        pex_path: str,
        pex_args: Iterable[str],
        description: str,
        input_digest: Digest,
        env: Optional[Mapping[str, str]] = None,
        **kwargs: Any,
    ) -> Process:
        """Creates an Process that will run a PEX hermetically.

        :param pex_environment: The environment needed to bootstrap the PEX runtime.
        :param subprocess_environment: The locale settings to use for the PEX invocation.
        :param pex_path: The path within `input_files` of the PEX file (or directory if a loose
                         pex).
        :param pex_args: The arguments to pass to the PEX executable.
        :param description: A description of the process execution to be performed.
        :param input_digest: The directory digest that contains the PEX itself and any input files
                             it needs to run against.
        :param env: The environment to run the PEX in.
        :param **kwargs: Any additional :class:`Process` kwargs to pass through.
        """

        # TODO(#7735): Set --python-setup-interpreter-search-paths differently for the host and target
        # platforms, when we introduce platforms in https://github.com/pantsbuild/pants/issues/7735.
        argv = pex_environment.create_argv(pex_path, *pex_args)

        hermetic_env = dict(
            PEX_INHERIT_PATH="false",
            PEX_IGNORE_RCFILES="true",
            **pex_environment.environment_dict,
            **subprocess_environment.environment_dict,
        )
        if env:
            hermetic_env.update(env)

        return Process(
            argv=argv,
            input_digest=input_digest,
            description=description,
            env=hermetic_env,
            **kwargs,
        )


def rules():
    return [*collect_rules(), *process.rules()]
