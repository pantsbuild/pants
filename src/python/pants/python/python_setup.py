# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, cast

from pex.variables import Variables

from pants.base.build_environment import get_buildroot
from pants.engine.environment import Environment
from pants.option.custom_types import file_option
from pants.option.subsystem import Subsystem
from pants.util.docutil import doc_url
from pants.util.memo import memoized_method
from pants.util.osutil import CPU_COUNT

logger = logging.getLogger(__name__)


class PythonSetup(Subsystem):
    options_scope = "python-setup"
    help = "Options for Pants's Python support."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--interpreter-constraints",
            advanced=True,
            type=list,
            default=["CPython>=3.6"],
            metavar="<requirement>",
            help=(
                "The Python interpreters your codebase is compatible with.\n\nSpecify with "
                "requirement syntax, e.g. 'CPython>=2.7,<3' (A CPython interpreter with version "
                ">=2.7 AND version <3) or 'PyPy' (A pypy interpreter of any version). Multiple "
                "constraint strings will be ORed together.\n\nThese constraints are used as the "
                "default value for the `interpreter_constraints` field of Python targets."
            ),
        )
        register(
            "--interpreter-versions-universe",
            advanced=True,
            type=list,
            default=["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"],
            help=(
                "All known Python major/minor interpreter versions that may be used by either "
                "your code or tools used by your code.\n\n"
                "This is used by Pants to robustly handle interpreter constraints, such as knowing "
                "when telling MyPy which version to run with which Python versions to check if "
                "your code is using.\n\n"
                "This does not control which interpreter your code will use. Instead, to set your "
                "interpreter constraints, update `[python-setup].interpreter_constraints`, the "
                "`interpreter_constraints` field, and relevant tool options like "
                "`[isort].interpreter_constraints` to tell Pants which interpreters your code "
                f"actually uses. See {doc_url('python-interpreter-compatibility')}.\n\n"
                "All elements must be the minor and major Python version, e.g. '2.7' or '3.10'. Do "
                "not include the patch version.\n\n"
            ),
        )
        register(
            "--requirement-constraints",
            advanced=True,
            type=file_option,
            help=(
                "When resolving third-party requirements, use this "
                "constraints file to determine which versions to use.\n\nSee "
                "https://pip.pypa.io/en/stable/user_guide/#constraints-files for more information "
                "on the format of constraint files and how constraints are applied in Pex and pip."
                "\n\nMutually exclusive with `--requirement-constraints-target`."
            ),
        )
        register(
            "--resolve-all-constraints",
            advanced=True,
            default=True,
            type=bool,
            help=(
                "If enabled, when resolving requirements, Pants will first resolve your entire "
                "constraints file as a single global resolve. Then, if the code uses a subset of "
                "your constraints file, Pants will extract the relevant requirements from that "
                "global resolve so that only what's actually needed gets used. If disabled, Pants "
                "will not use a global resolve and will resolve each subset of your requirements "
                "independently."
                "\n\nUsually this option should be enabled because it can result in far fewer "
                "resolves."
                "\n\nRequires [python-setup].requirement_constraints to be set."
            ),
        )
        register(
            "--interpreter-search-paths",
            advanced=True,
            type=list,
            default=["<PYENV>", "<PATH>"],
            metavar="<binary-paths>",
            help=(
                "A list of paths to search for Python interpreters that match your project's "
                "interpreter constraints. You can specify absolute paths to interpreter binaries "
                "and/or to directories containing interpreter binaries. The order of entries does "
                "not matter. The following special strings are supported:\n\n"
                '* "<PATH>", the contents of the PATH env var\n'
                '* "<PYENV>", all Python versions under $(pyenv root)/versions\n'
                '* "<PYENV_LOCAL>", the Pyenv interpreter with the version in '
                "BUILD_ROOT/.python-version\n"
                '* "<PEXRC>", paths in the PEX_PYTHON_PATH variable in /etc/pexrc or ~/.pexrc'
            ),
        )
        register(
            "--resolver-manylinux",
            advanced=True,
            type=str,
            default="manylinux2014",
            help="Whether to allow resolution of manylinux wheels when resolving requirements for "
            "foreign linux platforms. The value should be a manylinux platform upper bound, "
            "e.g.: 'manylinux2010', or else the string 'no' to disallow.",
        )
        register(
            "--resolver-jobs",
            type=int,
            default=CPU_COUNT // 2,
            default_help_repr="#cores/2",
            advanced=True,
            help=(
                "The maximum number of concurrent jobs to build wheels with.\n\nBecause Pants "
                "can run multiple subprocesses in parallel, the maximum total parallelism will be "
                "`--process-execution-{local,remote}-parallelism x --python-setup-resolver-jobs`. "
                "\n\nSetting this option higher may result in better parallelism, but, if set too "
                "high, may result in starvation and Out of Memory errors."
            ),
        )

    @property
    def interpreter_constraints(self) -> Tuple[str, ...]:
        return tuple(self.options.interpreter_constraints)

    @property
    def interpreter_universe(self) -> tuple[str, ...]:
        return tuple(self.options.interpreter_versions_universe)

    @property
    def requirement_constraints(self) -> str | None:
        """Path to constraint file."""
        return cast("str | None", self.options.requirement_constraints)

    @property
    def resolve_all_constraints(self) -> bool:
        return cast(bool, self.options.resolve_all_constraints)

    def resolve_all_constraints_was_set_explicitly(self) -> bool:
        return not self.options.is_default("resolve_all_constraints")

    @memoized_method
    def interpreter_search_paths(self, env: Environment):
        return self.expand_interpreter_search_paths(self.options.interpreter_search_paths, env)

    @property
    def manylinux(self) -> Optional[str]:
        manylinux = cast(Optional[str], self.options.resolver_manylinux)
        if manylinux is None or manylinux.lower() in ("false", "no", "none"):
            return None
        return manylinux

    @property
    def resolver_jobs(self) -> int:
        return cast(int, self.options.resolver_jobs)

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
    def expand_interpreter_search_paths(cls, interpreter_search_paths, env: Environment):
        special_strings = {
            "<PEXRC>": cls.get_pex_python_paths,
            "<PATH>": lambda: cls.get_environment_paths(env),
            "<PYENV>": lambda: cls.get_pyenv_paths(env),
            "<PYENV_LOCAL>": lambda: cls.get_pyenv_paths(env, pyenv_local=True),
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
    def get_environment_paths(env: Environment):
        """Returns a list of paths specified by the PATH env var."""
        pathstr = env.get("PATH")
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
    def get_pyenv_paths(env: Environment, *, pyenv_local: bool = False) -> List[str]:
        """Returns a list of paths to Python interpreters managed by pyenv.

        :param env: The environment to use to look up pyenv.
        :param bool pyenv_local: If True, only use the interpreter specified by
                                 '.python-version' file under `build_root`.
        """
        pyenv_root = get_pyenv_root(env)
        if not pyenv_root:
            return []

        versions_dir = Path(pyenv_root, "versions")
        if not versions_dir.is_dir():
            return []

        if pyenv_local:
            local_version_file = Path(get_buildroot(), ".python-version")
            if not local_version_file.exists():
                logger.warning(
                    "No `.python-version` file found in the build root, "
                    "but <PYENV_LOCAL> was set in `[python-setup].interpreter_search_paths`."
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


def get_pyenv_root(env: Environment) -> str | None:
    """See https://github.com/pyenv/pyenv#environment-variables."""
    from_env = env.get("PYENV_ROOT")
    if from_env:
        return from_env
    home_from_env = env.get("HOME")
    if home_from_env:
        return os.path.join(home_from_env, ".pyenv")
    return None
