# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path, PurePath

from pex.variables import Variables

from pants.base.build_environment import get_buildroot
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.rules import Get, collect_rules, rule
from pants.option.option_types import StrListOption
from pants.option.option_value_container import OptionValueContainer
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_method

logger = logging.getLogger(__name__)


class PythonBootstrapSubsystem(Subsystem):
    options_scope = "python-bootstrap"
    help = (
        "Options used to locate Python interpreters used by all Pants backends."
        "\n\n"
        "This subsystem controls where and how Pants will locate Python, but beyond that it does "
        "not control which Python interpreter versions are actually used for your code: see the "
        "`python` subsystem for that."
    )

    search_path = StrListOption(
        "--search-path",
        default=["<PYENV>", "<PATH>"],
        help=(
            "A list of paths to search for Python interpreters.\n\n"
            "Which interpeters are actually used from these paths is context-specific: "
            "the Python backend selects interpreters using options on the `python` subsystem, "
            "in particular, the `[python].interpreter_constraints` option.\n\n"
            "You can specify absolute paths to interpreter binaries "
            "and/or to directories containing interpreter binaries. The order of entries does "
            "not matter.\n\n"
            "The following special strings are supported:\n\n"
            "* `<PATH>`, the contents of the PATH env var\n"
            "* `<ASDF>`, all Python versions currently configured by ASDF "
            "`(asdf shell, ${HOME}/.tool-versions)`, with a fallback to all installed versions\n"
            "* `<ASDF_LOCAL>`, the ASDF interpreter with the version in "
            "BUILD_ROOT/.tool-versions\n"
            "* `<PYENV>`, all Python versions under $(pyenv root)/versions\n"
            "* `<PYENV_LOCAL>`, the Pyenv interpreter with the version in "
            "BUILD_ROOT/.python-version\n"
            "* `<PEXRC>`, paths in the PEX_PYTHON_PATH variable in /etc/pexrc or ~/.pexrc"
        ),
        advanced=True,
        metavar="<binary-paths>",
    )
    names = StrListOption(
        "--names",
        default=["python", "python3"],
        help=(
            "The names of Python binaries to search for. See the `--search-path` option to "
            "influence where interpreters are searched for.\n\n"
            "This does not impact which Python interpreter is used to run your code, only what "
            "is used to run internal tools."
        ),
        advanced=True,
        metavar="<python-binary-names>",
    )


@dataclass(frozen=True)
class PythonBootstrap:
    environment: Environment
    options: OptionValueContainer

    @property
    def interpreter_names(self) -> tuple[str, ...]:
        return tuple(self.options.names)

    @memoized_method
    def interpreter_search_paths(self):
        return self._expand_interpreter_search_paths(self.options.search_path, self.environment)

    @classmethod
    def _expand_interpreter_search_paths(cls, interpreter_search_paths, env: Environment):
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
    def get_asdf_paths(env: Environment, *, asdf_local: bool = False) -> list[str]:
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
        asdf_installed_paths: list[str] = []
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

        asdf_paths: list[str] = []
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
                    " `[python-bootstrap].search_paths`."
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
                                "`[python-bootstrap].search_path`, ignoring. This "
                                "version will not be considered when determining which Python "
                                f"interpreters to use. Please check that `{tool_versions_file}` "
                                "is accurate."
                            )
                    elif v == "system":
                        logger.warning(
                            "System python set by ASDF configured by "
                            "`[python-bootstrap].search_path` is unsupported, ignoring. "
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
                    f"`[python-bootstrap].search_path` but `{install_dir}` does not "
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
    def get_pyenv_paths(env: Environment, *, pyenv_local: bool = False) -> list[str]:
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
                    "but <PYENV_LOCAL> was set in `[python-bootstrap].search_path`."
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


@rule
async def python_bootstrap(python_bootstrap_subsystem: PythonBootstrapSubsystem) -> PythonBootstrap:
    environment = await Get(
        Environment, EnvironmentRequest(["PATH", "HOME", "PYENV_ROOT", "ASDF_DIR", "ASDF_DATA_DIR"])
    )
    return PythonBootstrap(environment, python_bootstrap_subsystem.options)


def rules():
    return collect_rules()
