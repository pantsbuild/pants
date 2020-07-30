# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import subprocess
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple, cast

from pex.variables import Variables

from pants.base.build_environment import get_buildroot
from pants.option.custom_types import UnsetBool, file_option
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_property

logger = logging.getLogger(__name__)


class PythonSetup(Subsystem):
    """A Python environment."""

    options_scope = "python-setup"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--interpreter-constraints",
            advanced=True,
            type=list,
            default=["CPython>=3.6"],
            metavar="<requirement>",
            help="Constrain the selected Python interpreter. Specify with requirement syntax, "
            "e.g. 'CPython>=2.7,<3' (A CPython interpreter with version >=2.7 AND version <3)"
            "or 'PyPy' (A pypy interpreter of any version). Multiple constraint strings will "
            "be ORed together. These constraints are applied in addition to any "
            "compatibilities required by the relevant targets.",
        )
        register(
            "--requirement-constraints",
            advanced=True,
            type=file_option,
            help=(
                "When resolving third-party requirements, use this "
                "constraint file to determine which versions to use. See "
                "https://pip.pypa.io/en/stable/user_guide/#constraints-files for more information "
                "on the format of constraint files and how constraints are applied in Pex and Pip."
            ),
        )
        register(
            "--resolve-all-constraints",
            advanced=True,
            default=False,
            type=bool,
            help=(
                "If set, and the requirements of the code being operated on are a subset of the "
                "constraints file, then the entire constraints file will be used instead of the "
                "subset. If unset, or any requirement of the code being operated on is not in the "
                "constraints file, each subset will be independently resolved as needed, which is "
                "more correct - work is only invalidated if a requirement it actually depends on "
                "changes - but also a lot slower, due to the extra resolving. "
                "You may wish to leave this option set for normal work, such as running tests, "
                "but selectively turn it off via command-line-flag when building deployable "
                "binaries, so that you only deploy the requirements you actually need for a "
                "given binary."
            ),
        )
        register(
            "--platforms",
            advanced=True,
            type=list,
            metavar="<platform>",
            default=["current"],
            help="A list of platforms to be supported by this Python environment. Each platform"
            "is a string, as returned by pkg_resources.get_supported_platform().",
        )
        register(
            "--interpreter-cache-dir",
            advanced=True,
            default=None,
            metavar="<dir>",
            help="The parent directory for the interpreter cache. "
            "If unspecified, a standard path under the workdir is used.",
            removal_version="2.1.0.dev0",
            removal_hint=(
                "The option `--python-setup-interpreter-cache-dir` does not do anything anymore."
            ),
        )
        register(
            "--resolver-cache-dir",
            advanced=True,
            default=None,
            metavar="<dir>",
            help="The parent directory for the requirement resolver cache. "
            "If unspecified, a standard path under the workdir is used.",
            removal_version="2.1.0.dev0",
            removal_hint=(
                "The option `--python-setup-resolver-cache-dir` does not do anything anymore."
            ),
        )
        register(
            "--resolver-allow-prereleases",
            advanced=True,
            type=bool,
            default=UnsetBool,
            help="Whether to include pre-releases when resolving requirements.",
        )
        register(
            "--interpreter-search-paths",
            advanced=True,
            type=list,
            default=["<PEXRC>", "<PATH>"],
            metavar="<binary-paths>",
            help="A list of paths to search for python interpreters. The following special "
            "strings are supported: "
            '"<PATH>" (the contents of the PATH env var), '
            '"<PEXRC>" (paths in the PEX_PYTHON_PATH variable in a pexrc file), '
            '"<PYENV>" (all python versions under $(pyenv root)/versions).'
            '"<PYENV_LOCAL>" (the python version in BUILD_ROOT/.python-version).',
        )
        register(
            "--resolver-manylinux",
            advanced=True,
            type=str,
            default="manylinux2014",
            help="Whether to allow resolution of manylinux wheels when resolving requirements for "
            "foreign linux platforms. The value should be a manylinux platform upper bound, "
            "e.g.: manylinux2010, or else [Ff]alse, [Nn]o or [Nn]one to disallow.",
        )
        register(
            "--resolver-jobs",
            type=int,
            default=None,
            advanced=True,
            help="The maximum number of concurrent jobs to resolve wheels with.",
        )

    @property
    def interpreter_constraints(self) -> Tuple[str, ...]:
        return tuple(self.options.interpreter_constraints)

    @property
    def requirement_constraints(self) -> Optional[str]:
        """Path to constraint file."""
        return cast(Optional[str], self.options.requirement_constraints)

    @property
    def resolve_all_constraints(self) -> bool:
        return cast(bool, self.options.resolve_all_constraints)

    @memoized_property
    def interpreter_search_paths(self):
        return self.expand_interpreter_search_paths(self.options.interpreter_search_paths)

    @property
    def platforms(self):
        return self.options.platforms

    @property
    def interpreter_cache_dir(self):
        return self.options.interpreter_cache_dir or os.path.join(self.scratch_dir, "interpreters")

    @property
    def resolver_cache_dir(self):
        return self.options.resolver_cache_dir or os.path.join(
            self.scratch_dir, "resolved_requirements"
        )

    @property
    def resolver_allow_prereleases(self):
        return self.options.resolver_allow_prereleases

    @property
    def manylinux(self):
        manylinux = self.options.resolver_manylinux
        if manylinux is None or manylinux.lower() in ("false", "no", "none"):
            return None
        return manylinux

    @property
    def resolver_jobs(self):
        return self.options.resolver_jobs

    @property
    def scratch_dir(self):
        return os.path.join(self.options.pants_workdir, *self.options_scope.split("."))

    def compatibility_or_constraints(
        self, compatibility: Optional[Iterable[str]]
    ) -> Tuple[str, ...]:
        """Return either the given `compatibility` field or the global interpreter constraints.

        If interpreter constraints are supplied by the CLI flag, return those only.
        """
        if self.options.is_flagged("interpreter_constraints"):
            return self.interpreter_constraints
        return tuple(compatibility or self.interpreter_constraints)

    def compatibilities_or_constraints(
        self, compatibilities: Iterable[Optional[Iterable[str]]]
    ) -> Tuple[str, ...]:
        return tuple(
            constraint
            for compatibility in compatibilities
            for constraint in self.compatibility_or_constraints(compatibility)
        )

    @classmethod
    def expand_interpreter_search_paths(cls, interpreter_search_paths, pyenv_root_func=None):
        special_strings = {
            "<PEXRC>": cls.get_pex_python_paths,
            "<PATH>": cls.get_environment_paths,
            "<PYENV>": lambda: cls.get_pyenv_paths(pyenv_root_func=pyenv_root_func),
            "<PYENV_LOCAL>": lambda: cls.get_pyenv_paths(
                pyenv_root_func=pyenv_root_func, pyenv_local=True
            ),
        }
        expanded = []
        from_pexrc = None
        for s in interpreter_search_paths:
            if s in special_strings:
                special_paths = special_strings[s]()
                if s == "<PEXRC>":
                    from_pexrc = special_paths
                expanded.extend(special_paths)
            else:
                expanded.append(s)
        # Some special-case logging to avoid misunderstandings.
        if from_pexrc and len(expanded) > len(from_pexrc):
            logger.info(
                "pexrc interpreters requested and found, but other paths were also specified, "
                "so interpreters may not be restricted to the pexrc ones. Full search path is: "
                "{}".format(":".join(expanded))
            )
        return expanded

    @staticmethod
    def get_environment_paths():
        """Returns a list of paths specified by the PATH env var."""
        pathstr = os.getenv("PATH")
        if pathstr:
            return pathstr.split(os.pathsep)
        return []

    @staticmethod
    def get_pex_python_paths():
        """Returns a list of paths to Python interpreters as defined in a pexrc file.

        These are provided by a PEX_PYTHON_PATH in either of '/etc/pexrc', '~/.pexrc'.
        PEX_PYTHON_PATH defines a colon-separated list of paths to interpreters that a pex can be
        built and run against.
        """
        ppp = Variables.from_rc().get("PEX_PYTHON_PATH")
        if ppp:
            return ppp.split(os.pathsep)
        else:
            return []

    @staticmethod
    def get_pyenv_paths(
        *, pyenv_root_func: Optional[Callable] = None, pyenv_local: bool = False
    ) -> List[str]:
        """Returns a list of paths to Python interpreters managed by pyenv.

        :param pyenv_root_func: A no-arg function that returns the pyenv root. Defaults to
                                running `pyenv root`, but can be overridden for testing.
        :param bool pyenv_local: If True, only use the interpreter specified by
                                 '.python-version' file under `build_root`.
        """
        pyenv_root_func = pyenv_root_func or get_pyenv_root
        pyenv_root = pyenv_root_func()
        if pyenv_root is None:
            return []
        versions_dir = Path(pyenv_root, "versions")

        if pyenv_local:

            local_version_file = Path(get_buildroot(), ".python-version")
            if not local_version_file.exists():
                logger.info(
                    "No `.python-version` file found in the build root, "
                    "but <PYENV_LOCAL> was set in `--python-setup-interpreter-constraints`."
                )
                return []

            local_version = local_version_file.read_text().strip()
            path = Path(versions_dir, local_version, "bin")
            if path.is_dir():
                return [str(path)]
            return []

        paths = []
        for version in sorted(versions_dir.iterdir()):
            path = Path(versions_dir, version, "bin")
            if path.is_dir():
                paths.append(str(path))
        return paths


def get_pyenv_root():
    try:
        return subprocess.check_output(["pyenv", "root"]).decode().strip()
    except (OSError, subprocess.CalledProcessError):
        logger.info("No pyenv binary found. Will not use pyenv interpreters.")
    return None
