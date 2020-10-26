# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from typing import Mapping, Optional, Tuple, cast

from pants.core.util_rules import subprocess_environment
from pants.core.util_rules.subprocess_environment import SubprocessEnvironmentVars
from pants.engine import process
from pants.engine.engine_aware import EngineAwareReturnType
from pants.engine.process import BinaryPath, BinaryPathRequest, BinaryPaths, BinaryPathTest
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.option.global_options import GlobalOptions
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
        register(
            "--verbosity",
            advanced=True,
            type=int,
            default=0,
            help="Set the verbosity level of PEX logging, from 0 (no logging) up to 9 (max logging).",
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

    @property
    def verbosity(self) -> int:
        level = cast(int, self.options.verbosity)
        if level < 0 or level > 9:
            raise ValueError("verbosity level must be between 0 and 9")
        return level


class PythonExecutable(BinaryPath, EngineAwareReturnType):
    """The BinaryPath of a Python executable."""

    def message(self) -> str:
        return f"Selected {self.path} to run PEXes with."


@dataclass(frozen=True)
class PexEnvironment(EngineAwareReturnType):
    path: Tuple[str, ...]
    interpreter_search_paths: Tuple[str, ...]
    subprocess_environment_dict: FrozenDict[str, str]
    named_caches_dir: str
    bootstrap_python: Optional[PythonExecutable] = None

    def create_argv(
        self, pex_filepath: str, *args: str, python: Optional[PythonExecutable] = None
    ) -> Tuple[str, ...]:
        python = python or self.bootstrap_python
        argv = [python.path] if python else []
        argv.append(pex_filepath)
        argv.extend(args)
        return tuple(argv)

    def environment_dict(self, *, python_configured: bool) -> Mapping[str, str]:
        """The environment to use for running anything with PEX.

        If the Process is run with a pre-selected Python interpreter, set `python_configured=True`
        to avoid PEX from trying to find a new interpreter.
        """
        d = dict(
            PATH=create_path_env_var(self.path),
            PEX_INHERIT_PATH="false",
            PEX_IGNORE_RCFILES="true",
            PEX_ROOT=os.path.join(self.named_caches_dir, "pex_root"),
            **self.subprocess_environment_dict,
        )
        # NB: We only set `PEX_PYTHON_PATH` if the Python interpreter has not already been
        # pre-selected by Pants. Otherwise, Pex would inadvertently try to find another interpreter
        # when running PEXes. (Creating a PEX will ignore this env var in favor of `--python-path`.)
        if not python_configured:
            d["PEX_PYTHON_PATH"] = create_path_env_var(self.interpreter_search_paths)
        return d

    def level(self) -> LogLevel:
        return LogLevel.DEBUG if self.bootstrap_python else LogLevel.WARN

    def message(self) -> str:
        if not self.bootstrap_python:
            return (
                "No bootstrap Python executable could be found from the option "
                "`interpreter_search_paths` in the `[python-setup]` scope. Will attempt to run "
                "PEXes directly."
            )
        return f"Selected {self.bootstrap_python.path} to bootstrap PEXes with."


@rule(desc="Find Python interpreter to bootstrap PEX", level=LogLevel.DEBUG)
async def find_pex_python(
    python_setup: PythonSetup,
    pex_runtime_env: PexRuntimeEnvironment,
    subprocess_env_vars: SubprocessEnvironmentVars,
    global_options: GlobalOptions,
) -> PexEnvironment:
    # PEX files are compatible with bootstrapping via Python 2.7 or Python 3.5+. The bootstrap
    # code will then re-exec itself if the underlying PEX user code needs a more specific python
    # interpreter. As such, we look for many Pythons usable by the PEX bootstrap code here for
    # maximum flexibility.
    all_python_binary_paths = await MultiGet(
        Get(
            BinaryPaths,
            BinaryPathRequest(
                search_path=python_setup.interpreter_search_paths,
                binary_name=binary_name,
                test=BinaryPathTest(
                    args=[
                        "-c",
                        # N.B.: The following code snippet must be compatible with Python 2.7 and
                        # Python 3.5+.
                        #
                        # We hash the underlying Python interpreter executable to ensure we detect
                        # changes in the real interpreter that might otherwise be masked by Pyenv
                        # shim scripts found on the search path. Naively, just printing out the full
                        # version_info would be enough, but that does not account for supported abi
                        # changes (e.g.: a pyenv switch from a py27mu interpreter to a py27m
                        # interpreter.)
                        #
                        # When hashing, we pick 8192 for efficiency of reads and fingerprint updates
                        # (writes) since it's a common OS buffer size and an even multiple of the
                        # hash block size.
                        dedent(
                            """\
                            import sys

                            major, minor = sys.version_info[:2]
                            if (major, minor) != (2, 7) and not (major == 3 and minor >= 5):
                                sys.exit(1)

                            import hashlib
                            hasher = hashlib.sha256()
                            with open(sys.executable, "rb") as fp:
                                for chunk in iter(lambda: fp.read(8192), b""):
                                    hasher.update(chunk)
                            sys.stdout.write(hasher.hexdigest())
                            """
                        ),
                    ],
                    fingerprint_stdout=False,  # We already emit a usable fingerprint to stdout.
                ),
            ),
        )
        for binary_name in pex_runtime_env.bootstrap_interpreter_names
    )

    def first_python_binary() -> Optional[PythonExecutable]:
        for binary_paths in all_python_binary_paths:
            if binary_paths.first_path:
                return PythonExecutable(
                    path=binary_paths.first_path.path,
                    fingerprint=binary_paths.first_path.fingerprint,
                )
        return None

    return PexEnvironment(
        path=pex_runtime_env.path,
        interpreter_search_paths=tuple(python_setup.interpreter_search_paths),
        subprocess_environment_dict=subprocess_env_vars.vars,
        # TODO: This path normalization is duplicated with `engine_initializer.py`. How can we do
        #  the normalization only once, via the options system?
        named_caches_dir=Path(global_options.options.named_caches_dir).resolve().as_posix(),
        bootstrap_python=first_python_binary(),
    )


def rules():
    return [*collect_rules(), *process.rules(), *subprocess_environment.rules()]
