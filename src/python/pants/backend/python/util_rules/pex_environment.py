# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePath
from typing import Mapping

from pants.core.subsystems.python_bootstrap import PythonBootstrap
from pants.core.util_rules import subprocess_environment, system_binaries
from pants.core.util_rules.subprocess_environment import SubprocessEnvironmentVars
from pants.core.util_rules.system_binaries import BinaryPath, PythonBinary
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.environment import Environment
from pants.engine.rules import collect_rules, rule
from pants.option.global_options import NamedCachesDirOption
from pants.option.option_types import BoolOption, IntOption, StrListOption
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized_method
from pants.util.ordered_set import OrderedSet
from pants.util.strutil import create_path_env_var, softwrap


class PexRuntimeEnvironment(Subsystem):
    options_scope = "pex"
    help = "How Pants uses Pex to run Python subprocesses."

    # TODO(#9760): We'll want to deprecate this in favor of a global option which allows for a
    #  per-process override.
    _executable_search_paths = StrListOption(
        default=["<PATH>"],
        help=softwrap(
            """
            The PATH value that will be used by the PEX subprocess and any subprocesses it
            spawns.

            The special string `"<PATH>"` will expand to the contents of the PATH env var.
            """
        ),
        advanced=True,
        metavar="<binary-paths>",
    )
    _verbosity = IntOption(
        default=0,
        help="Set the verbosity level of PEX logging, from 0 (no logging) up to 9 (max logging).",
        advanced=True,
    )
    venv_use_symlinks = BoolOption(
        default=False,
        help=softwrap(
            """
            When possible, use venvs whose site-packages directories are populated with symlinks.

            Enabling this can save space in the `--named-caches-dir` directory
            and lead to slightly faster execution times for Pants Python goals. Some
            distributions do not work with symlinked venvs though, so you may not be able to
            enable this optimization as a result.
            """
        ),
        advanced=True,
    )

    @memoized_method
    def path(self, env: Environment) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self._executable_search_paths:
                if entry == "<PATH>":
                    path = env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))

    @property
    def verbosity(self) -> int:
        level = self._verbosity
        if level < 0 or level > 9:
            raise ValueError("verbosity level must be between 0 and 9")
        return level


class PythonExecutable(BinaryPath, EngineAwareReturnType):
    """The BinaryPath of a Python executable."""

    def message(self) -> str:
        return f"Selected {self.path} to run PEXes with."

    @classmethod
    def from_python_binary(cls, python_binary: PythonBinary) -> PythonExecutable:
        """Converts from PythonBinary to PythonExecutable.

        The PythonBinary type is a singleton representing the Python that is used for script
        execution by `@rule`s. On the other hand, there may be multiple PythonExecutables, since
        they are subject to a user's interpreter constraints.
        """
        return cls(path=python_binary.path, fingerprint=python_binary.fingerprint)


@dataclass(frozen=True)
class PexEnvironment(EngineAwareReturnType):
    path: tuple[str, ...]
    interpreter_search_paths: tuple[str, ...]
    subprocess_environment_dict: FrozenDict[str, str]
    named_caches_dir: PurePath
    bootstrap_python: PythonExecutable | None = None
    venv_use_symlinks: bool = False

    _PEX_ROOT_DIRNAME = "pex_root"

    def level(self) -> LogLevel:
        return LogLevel.DEBUG if self.bootstrap_python else LogLevel.WARN

    def message(self) -> str:
        if not self.bootstrap_python:
            return softwrap(
                """
                No bootstrap Python executable could be found from the option
                `interpreter_search_paths` in the `[python]` scope. Will attempt to run
                PEXes directly.
                """
            )
        return f"Selected {self.bootstrap_python.path} to bootstrap PEXes with."

    def in_sandbox(self, *, working_directory: str | None) -> CompletePexEnvironment:
        pex_root = PurePath(".cache") / self._PEX_ROOT_DIRNAME
        return CompletePexEnvironment(
            _pex_environment=self,
            pex_root=pex_root,
            _working_directory=PurePath(working_directory) if working_directory else None,
            append_only_caches=FrozenDict({self._PEX_ROOT_DIRNAME: str(pex_root)}),
        )

    def in_workspace(self) -> CompletePexEnvironment:
        # N.B.: When running in the workspace the engine doesn't offer an append_only_caches
        # service to setup a symlink to our named cache for us. As such, we point the PEX_ROOT
        # directly at the underlying append only cache in that case to re-use results there and
        # to keep the workspace from being dirtied by the creation of a new Pex cache rooted
        # there.
        pex_root = self.named_caches_dir / self._PEX_ROOT_DIRNAME
        return CompletePexEnvironment(
            _pex_environment=self,
            pex_root=pex_root,
            _working_directory=None,
            append_only_caches=FrozenDict(),
        )

    def venv_site_packages_copies_option(self, use_copies: bool) -> str:
        if self.venv_use_symlinks and not use_copies:
            return "--no-venv-site-packages-copies"
        return "--venv-site-packages-copies"


@rule(desc="Prepare environment for running PEXes", level=LogLevel.DEBUG)
async def find_pex_python(
    python_bootstrap: PythonBootstrap,
    python_binary: PythonBinary,
    pex_runtime_env: PexRuntimeEnvironment,
    subprocess_env_vars: SubprocessEnvironmentVars,
    named_caches_dir: NamedCachesDirOption,
) -> PexEnvironment:
    return PexEnvironment(
        path=pex_runtime_env.path(python_bootstrap.environment),
        interpreter_search_paths=tuple(python_bootstrap.interpreter_search_paths()),
        subprocess_environment_dict=subprocess_env_vars.vars,
        named_caches_dir=named_caches_dir.val,
        bootstrap_python=PythonExecutable.from_python_binary(python_binary),
        venv_use_symlinks=pex_runtime_env.venv_use_symlinks,
    )


@dataclass(frozen=True)
class CompletePexEnvironment:
    _pex_environment: PexEnvironment
    pex_root: PurePath
    _working_directory: PurePath | None
    append_only_caches: FrozenDict[str, str]

    _PEX_ROOT_DIRNAME = "pex_root"

    @property
    def interpreter_search_paths(self) -> tuple[str, ...]:
        return self._pex_environment.interpreter_search_paths

    def create_argv(
        self, pex_filepath: str, *args: str, python: PythonExecutable | None = None
    ) -> tuple[str, ...]:
        pex_relpath = (
            os.path.relpath(pex_filepath, self._working_directory)
            if self._working_directory
            else pex_filepath
        )
        python = python or self._pex_environment.bootstrap_python
        if python:
            return (python.path, pex_relpath, *args)
        if os.path.basename(pex_relpath) == pex_relpath:
            return (f"./{pex_relpath}", *args)
        return (pex_relpath, *args)

    def environment_dict(self, *, python_configured: bool) -> Mapping[str, str]:
        """The environment to use for running anything with PEX.

        If the Process is run with a pre-selected Python interpreter, set `python_configured=True`
        to avoid PEX from trying to find a new interpreter.
        """
        d = dict(
            PATH=create_path_env_var(self._pex_environment.path),
            PEX_IGNORE_RCFILES="true",
            PEX_ROOT=(
                os.path.relpath(self.pex_root, self._working_directory)
                if self._working_directory
                else str(self.pex_root)
            ),
            **self._pex_environment.subprocess_environment_dict,
        )
        # NB: We only set `PEX_PYTHON_PATH` if the Python interpreter has not already been
        # pre-selected by Pants. Otherwise, Pex would inadvertently try to find another interpreter
        # when running PEXes. (Creating a PEX will ignore this env var in favor of `--python-path`.)
        if not python_configured:
            d["PEX_PYTHON_PATH"] = create_path_env_var(self.interpreter_search_paths)
        return d


def rules():
    return [
        *collect_rules(),
        *subprocess_environment.rules(),
        *system_binaries.rules(),
    ]
