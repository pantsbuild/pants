# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_info import PexInfo

from pants.option.optionable import Optionable
from pants.python.executable_pex_tool import ExecutablePexTool
from pants.python.python_requirement import PythonRequirement
from pants.util.contextutil import pushd
from pants.util.dirutil import safe_mkdtemp
from pants.util.memo import memoized_method
from pants.util.strutil import safe_shlex_join


class SetupPyRunner:
    """A utility capable of executing setup.py commands in a hermetic environment.

    Supports `setuptools` and `wheel` distutils commands by default.
    """

    class Factory(ExecutablePexTool):
        options_scope = "setup-py-runner"
        deprecated_options_scope = "build-setup-requires-pex"
        deprecated_options_scope_removal_version = "1.28.0.dev2"

        @classmethod
        def register_options(cls, register: Callable[..., None]) -> None:
            super().register_options(register)
            register(
                "--setuptools-version",
                advanced=True,
                fingerprint=True,
                default="44.0.0",
                help="The setuptools version to use when executing `setup.py` scripts.",
            )
            register(
                "--wheel-version",
                advanced=True,
                fingerprint=True,
                default="0.33.6",
                help="The wheel version to use when executing `setup.py` scripts.",
            )

        @classmethod
        def create(
            cls,
            *,
            pex_file_path: Optional[Path] = None,
            extra_reqs: Optional[List[PythonRequirement]] = None,
            interpreter: Optional[PythonInterpreter] = None,
            scope: Optional[Optionable] = None,
        ) -> "SetupPyRunner":
            factory = cls.scoped_instance(scope) if scope is not None else cls.global_instance()
            requirements_pex = factory.bootstrap(
                interpreter=interpreter,
                pex_file_path=pex_file_path or os.path.join(safe_mkdtemp(), "setup-py-runner.pex"),
                extra_reqs=extra_reqs,
            )
            return SetupPyRunner(requirements_pex=requirements_pex)

        @property
        def base_requirements(self):
            return [
                PythonRequirement(f"setuptools=={self.get_options().setuptools_version}"),
                PythonRequirement(f"wheel=={self.get_options().wheel_version}"),
            ]

    class CommandFailure(Exception):
        """Indicates an error executing setup.py commands."""

    def __init__(self, requirements_pex: PEX) -> None:
        self._requirements_pex = requirements_pex

    @memoized_method
    def __str__(self) -> str:
        pex_path = self._requirements_pex.path()
        pex_info = PexInfo.from_pex(pex_path)
        requirements = "\n  ".join(map(str, pex_info.requirements))
        return f"{type(self).__name__} at {pex_path} with requirements:\n  {requirements} "

    def _create_python_args(self, setup_command: Iterable[str]) -> Iterable[str]:
        args = ["setup.py", "--no-user-cfg"]
        args.extend(setup_command)
        return args

    def cmdline(self, setup_command: Iterable[str]) -> Iterable[str]:
        """Returns the command line that would be used to execute the given setup.py command."""
        args = self._create_python_args(setup_command)
        cmdline: List[str] = self._requirements_pex.cmdline(args)
        return cmdline

    def run_setup_command(
        self, *, source_dir: Path, setup_command: Iterable[str], **kwargs
    ) -> None:
        """Runs the given setup.py command against the setup.py project in `source_dir`.

        :raises: :class:`SetupPyRunner.CommandFailure` if there was a problem executing the command.
        """
        with pushd(str(source_dir)):
            result = self._requirements_pex.run(
                args=self._create_python_args(setup_command), **kwargs
            )
            if result != 0:
                pex_command = safe_shlex_join(self.cmdline(setup_command))
                raise self.CommandFailure(f"Failed to execute {pex_command} using {self}")

    def _collect_distribution(
        self, source_dir: Path, setup_command: Iterable[str], dist_dir: Path
    ) -> Path:

        assert source_dir.is_dir()
        self._source_dir = source_dir

        self.run_setup_command(source_dir=source_dir, setup_command=setup_command)

        dists = os.listdir(dist_dir)
        if len(dists) == 0:
            raise self.CommandFailure("No distribution was produced!")
        if len(dists) > 1:
            ambiguous_dists = "\n  ".join(dists)
            raise self.CommandFailure(f"Ambiguous distributions found:\n  {ambiguous_dists}")

        return dist_dir.joinpath(dists[0])

    @memoized_method
    def sdist(self, source_dir: Path) -> Path:
        """Generates an sdist from the setup.py project at `source_dir` and returns the sdist
        path."""
        dist_dir = safe_mkdtemp()
        return self._collect_distribution(
            source_dir=source_dir,
            setup_command=["sdist", "--dist-dir", dist_dir],
            dist_dir=Path(dist_dir),
        )

    @memoized_method
    def bdist(self, source_dir: Path) -> Path:
        """Generates a wheel from the setup.py project at `source_dir` and returns the wheel
        path."""
        dist_dir = safe_mkdtemp()
        return self._collect_distribution(
            source_dir=source_dir,
            setup_command=["bdist_wheel", "--dist-dir", dist_dir],
            dist_dir=Path(dist_dir),
        )
