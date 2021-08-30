# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import enum
import logging
import os
import re
from collections import OrderedDict
from pathlib import Path, PurePath
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


@enum.unique
class InvalidLockfileBehavior(enum.Enum):
    error = "error"
    ignore = "ignore"
    warn = "warn"


class PythonSetup(Subsystem):
    options_scope = "python-setup"
    help = "Options for Pants's Python support."

    default_interpreter_constraints = ["CPython>=3.6,<4"]
    default_interpreter_universe = ["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10"]

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--interpreter-constraints",
            advanced=True,
            type=list,
            default=PythonSetup.default_interpreter_constraints,
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
            default=cls.default_interpreter_universe,
            help=(
                "All known Python major/minor interpreter versions that may be used by either "
                "your code or tools used by your code.\n\n"
                "This is used by Pants to robustly handle interpreter constraints, such as knowing "
                "when generating lockfiles which Python versions to check if your code is "
                "using.\n\n"
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
            mutually_exclusive_group="lockfile",
            help=(
                "When resolving third-party requirements for your own code (vs. tools you run), "
                "use this constraints file to determine which versions to use.\n\n"
                "This only applies when resolving user requirements, rather than tools you run "
                "like Black and Pytest. To constrain tools, set `[tool].lockfile`, e.g. "
                "`[black].lockfile`.\n\n"
                "See https://pip.pypa.io/en/stable/user_guide/#constraints-files for more "
                "information on the format of constraint files and how constraints are applied in "
                "Pex and pip.\n\n"
                "Mutually exclusive with `[python-setup].experimental_lockfile`."
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
            "--experimental-lockfile",
            advanced=True,
            # TODO(#11719): Switch this to a file_option once env vars can unset a value.
            type=str,
            metavar="<file>",
            mutually_exclusive_group="constraints",
            help=(
                "The lockfile to use when resolving requirements for your own code (vs. tools you "
                "run).\n\n"
                "This is highly experimental and will change, including adding support for "
                "multiple lockfiles. This option's behavior may change without the normal "
                "deprecation cycle.\n\n"
                "To generate a lockfile, activate the backend `pants.backend.experimental.python`"
                "and run `./pants generate-user-lockfile ::`.\n\n"
                "Mutually exclusive with `[python-setup].requirement_constraints`."
            ),
        )
        register(
            "--invalid-lockfile-behavior",
            advanced=True,
            type=InvalidLockfileBehavior,
            default=InvalidLockfileBehavior.error,
            help=(
                "The behavior when a lockfile has requirements or interpreter constraints that are "
                "not compatible with what the current build is using.\n\n"
                "We recommend keeping the default of `error` for CI builds."
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
                '* "<ASDF>", all Python versions currently configured by ASDF '
                "(asdf shell, ${HOME}/.tool-versions), with a fallback to all installed versions\n"
                '* "<ASDF_LOCAL>", the ASDF interpreter with the version in '
                "BUILD_ROOT/.tool-versions\n"
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

        register(
            "--tailor-ignore-solitary-init-files",
            type=bool,
            default=True,
            advanced=True,
            help="Don't tailor python_library targets for solitary __init__.py files, as "
            "those usually exist as import scaffolding rather than true library code.\n\n"
            "Set to False if you commonly have packages containing real code in "
            "__init__.py and there are no other .py files in the package.",
        )

        register(
            "--tailor-pex-binary-targets",
            type=bool,
            default=True,
            advanced=True,
            help="Tailor pex_binary() targets for Python entry point files.",
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
    def lockfile(self) -> str | None:
        return cast("str | None", self.options.experimental_lockfile)

    @property
    def invalid_lockfile_behavior(self) -> InvalidLockfileBehavior:
        return cast(InvalidLockfileBehavior, self.options.invalid_lockfile_behavior)

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
    def tailor_ignore_solitary_init_files(self) -> bool:
        return cast(bool, self.options.tailor_ignore_solitary_init_files)

    @property
    def tailor_pex_binary_targets(self) -> bool:
        return cast(bool, self.options.tailor_pex_binary_targets)

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
            "<ASDF>": lambda: cls.get_asdf_paths(env),
            "<ASDF_LOCAL>": lambda: cls.get_asdf_paths(env, asdf_local=True),
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
    def get_asdf_paths(env: Environment, *, asdf_local: bool = False) -> List[str]:
        """Returns a list of paths to Python interpreters managed by ASDF.

        :param env: The environment to use to look up ASDF.
        :param bool asdf_local: If True, only use the interpreter specified by
                                '.tool-versions' file under `build_root`.
        """
        asdf_dir = get_asdf_data_dir(env)
        if not asdf_dir:
            return []

        asdf_dir = Path(asdf_dir)

        # Ignore ASDF if the python plugin isn't installed.
        asdf_python_plugin = asdf_dir / "plugins" / "python"
        if not asdf_python_plugin.exists():
            return []

        # Ignore ASDF if no python versions have ever been installed (the installs folder is
        # missing).
        asdf_installs_dir = asdf_dir / "installs" / "python"
        if not asdf_installs_dir.exists():
            return []

        # Find all installed versions.
        asdf_installed_paths: List[str] = []
        for child in asdf_installs_dir.iterdir():
            # Aliases, and non-cpython installs may have odd names.
            # Make sure that the entry is a subdirectory of the installs directory.
            if child.is_dir():
                # Make sure that the subdirectory has a bin directory.
                bin_dir = child / "bin"
                if bin_dir.exists():
                    asdf_installed_paths.append(str(bin_dir))

        # Ignore ASDF if there are no installed versions.
        if not asdf_installed_paths:
            return []

        asdf_paths: List[str] = []
        asdf_versions: OrderedDict[str, str] = OrderedDict()
        tool_versions_file = None

        # Support "shell" based ASDF configuration
        ASDF_PYTHON_VERSION = env.get("ASDF_PYTHON_VERSION")
        if ASDF_PYTHON_VERSION:
            asdf_versions.update(
                [(v, "ASDF_PYTHON_VERSION") for v in re.split(r"\s+", ASDF_PYTHON_VERSION)]
            )

        # Target the local tool-versions file.
        if asdf_local:
            tool_versions_file = Path(get_buildroot(), ".tool-versions")
            if not tool_versions_file.exists():
                logger.warning(
                    "No `.tool-versions` file found in the build root, but <ASDF_LOCAL> was set in"
                    " `[python-setup].interpreter_search_paths`."
                )
                tool_versions_file = None
        # Target the home directory tool-versions file.
        else:
            home = env.get("HOME")
            if home:
                tool_versions_file = Path(home) / ".tool-versions"
                if not tool_versions_file.exists():
                    tool_versions_file = None

        if tool_versions_file:
            # Parse the tool-versions file.
            # A tool-versions file contains multiple lines, one or more per tool.
            # Standardize that the last line for each tool wins.
            #
            # The definition of a tool-versions file can be found here:
            # https://asdf-vm.com/#/core-configuration?id=tool-versions
            tool_versions_lines = tool_versions_file.read_text().splitlines()
            last_line = None
            for line in tool_versions_lines:
                # Find the last python line.
                if line.lower().startswith("python"):
                    last_line = line
            if last_line:
                _, _, versions = last_line.partition("python")
                for v in re.split(r"\s+", versions.strip()):
                    if ":" in v:
                        key, _, value = v.partition(":")
                        if key.lower() == "path":
                            asdf_paths.append(value)
                        elif key.lower() == "ref":
                            asdf_versions[value] = str(tool_versions_file)
                        else:
                            logger.warning(
                                f"Unknown version format `{v}` from ASDF configured by "
                                "`[python-setup].interpreter_search_paths`, ignoring. This "
                                "version will not be considered when determining which Python "
                                f"interpreters to use. Please check that `{tool_versions_file}` "
                                "is accurate."
                            )
                    elif v == "system":
                        logger.warning(
                            "System python set by ASDF configured by "
                            "`[python-setup].interpreter_search_paths` is unsupported, ignoring. "
                            "This version will not be considered when determining which Python "
                            "interpreters to use. Please remove 'system' from "
                            f"`{tool_versions_file}` to disable this warning."
                        )
                    else:
                        asdf_versions[v] = str(tool_versions_file)

        for version, source in asdf_versions.items():
            install_dir = asdf_installs_dir / version / "bin"
            if install_dir.exists():
                asdf_paths.append(str(install_dir))
            else:
                logger.warning(
                    f"Trying to use ASDF version `{version}` configured by "
                    f"`[python-setup].interpreter_search_paths` but `{install_dir}` does not "
                    "exist. This version will not be considered when determining which Python "
                    f"interpreters to use. Please check that `{source}` is accurate."
                )

        # For non-local, if no paths have been defined, fallback to every version installed
        if not asdf_local and len(asdf_paths) == 0:
            # This could be appended to asdf_paths, but there isn't any reason to
            return asdf_installed_paths
        else:
            return asdf_paths

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


def get_asdf_data_dir(env: Environment) -> PurePath | None:
    """Returns the location of asdf's installed tool versions.

    See https://asdf-vm.com/manage/configuration.html#environment-variables.

    `ASDF_DATA_DIR` is an environment variable that can be set to override the directory
    in which the plugins, installs, and shims are installed.

    `ASDF_DIR` is another environment variable that can be set, but we ignore it since
    that location only specifies where the asdf tool itself is installed, not the managed versions.

    Per the documentation, if `ASDF_DATA_DIR` is not specified, the tool will fall back to
    `$HOME/.asdf`, so we do that as well.

    :param env: The environment to use to look up asdf.
    :return: Path to the data directory, or None if it couldn't be found in the environment.
    """
    asdf_data_dir = env.get("ASDF_DATA_DIR")
    if not asdf_data_dir:
        home = env.get("HOME")
        if home:
            return PurePath(home) / ".asdf"
    return PurePath(asdf_data_dir) if asdf_data_dir else None


def get_pyenv_root(env: Environment) -> str | None:
    """See https://github.com/pyenv/pyenv#environment-variables."""
    from_env = env.get("PYENV_ROOT")
    if from_env:
        return from_env
    home_from_env = env.get("HOME")
    if home_from_env:
        return os.path.join(home_from_env, ".pyenv")
    return None
