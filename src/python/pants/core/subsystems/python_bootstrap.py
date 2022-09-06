# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from pex.variables import Variables

from pants.base.build_environment import get_buildroot
from pants.core.util_rules import asdf
from pants.core.util_rules.asdf import AsdfToolPathsRequest, AsdfToolPathsResult
from pants.core.util_rules.environments import (
    EnvironmentsSubsystem,
    EnvironmentTarget,
    PythonBootstrapBinaryNamesField,
    PythonInterpreterSearchPathsField,
)
from pants.engine.environment import Environment
from pants.engine.rules import Get, collect_rules, rule
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
from pants.util.memo import memoized_method
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class PythonBootstrapSubsystem(Subsystem):
    options_scope = "python-bootstrap"
    help = softwrap(
        """
        Options used to locate Python interpreters used by all Pants backends.

        This subsystem controls where and how Pants will locate Python, but beyond that it does
        not control which Python interpreter versions are actually used for your code: see the
        `python` subsystem for that.
        """
    )

    search_path = StrListOption(
        default=["<PYENV>", "<PATH>"],
        help=softwrap(
            """
            A list of paths to search for Python interpreters.

            Which interpeters are actually used from these paths is context-specific:
            the Python backend selects interpreters using options on the `python` subsystem,
            in particular, the `[python].interpreter_constraints` option.

            You can specify absolute paths to interpreter binaries
            and/or to directories containing interpreter binaries. The order of entries does
            not matter.

            The following special strings are supported:

              * `<PATH>`, the contents of the PATH env var
              * `<ASDF>`, all Python versions currently configured by ASDF \
                  `(asdf shell, ${HOME}/.tool-versions)`, with a fallback to all installed versions
              * `<ASDF_LOCAL>`, the ASDF interpreter with the version in BUILD_ROOT/.tool-versions
              * `<PYENV>`, all Python versions under $(pyenv root)/versions
              * `<PYENV_LOCAL>`, the Pyenv interpreter with the version in BUILD_ROOT/.python-version
              * `<PEXRC>`, paths in the PEX_PYTHON_PATH variable in /etc/pexrc or ~/.pexrc
            """
        ),
        advanced=True,
        metavar="<binary-paths>",
    )
    names = StrListOption(
        default=["python", "python3"],
        help=softwrap(
            """
            The names of Python binaries to search for. See the `--search-path` option to
            influence where interpreters are searched for.

            This does not impact which Python interpreter is used to run your code, only what
            is used to run internal tools.
            """
        ),
        advanced=True,
        metavar="<python-binary-names>",
    )

    # TODO(#7735): Move to `Subsystem`?
    def error_if_environment_mechanism_ambiguity(self, option: str) -> None:
        if self.options.is_default(option):
            return
        raise ValueError(
            softwrap(
                f"""
                The option `[{self.options_scope}].{option}` is explicitly set at the same time as
                the option `[{EnvironmentsSubsystem.options_scope}].platforms_to_local_environment`,
                which makes it ambiguous which values to use. To fix, only set one of these options.
                """
            )
        )


@dataclass(frozen=True)
class PythonBootstrap:
    EXTRA_ENV_VAR_NAMES = ("PATH", "PYENV_ROOT")

    interpreter_names: tuple[str, ...]
    raw_interpreter_search_paths: tuple[str, ...]
    environment: Environment
    asdf_standard_tool_paths: tuple[str, ...]
    asdf_local_tool_paths: tuple[str, ...]

    @memoized_method
    def interpreter_search_paths(self):
        return self._expand_interpreter_search_paths(
            self.raw_interpreter_search_paths,
            self.environment,
            self.asdf_standard_tool_paths,
            self.asdf_local_tool_paths,
        )

    @classmethod
    def _expand_interpreter_search_paths(
        cls,
        interpreter_search_paths: Sequence[str],
        env: Environment,
        asdf_standard_tool_paths: tuple[str, ...],
        asdf_local_tool_paths: tuple[str, ...],
    ):
        special_strings = {
            "<PEXRC>": cls.get_pex_python_paths,
            "<PATH>": lambda: cls.get_environment_paths(env),
            "<ASDF>": lambda: asdf_standard_tool_paths,
            "<ASDF_LOCAL>": lambda: asdf_local_tool_paths,
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
    def contains_asdf_path_tokens(interpreter_search_paths: Iterable[str]) -> tuple[bool, bool]:
        """Returns tuple of whether the path list contains standard or local ASDF path tokens."""
        standard_path_token = False
        local_path_token = False
        for interpreter_search_path in interpreter_search_paths:
            if interpreter_search_path == "<ASDF>":
                standard_path_token = True
            elif interpreter_search_path == "<ASDF_LOCAL>":
                local_path_token = True
        return standard_path_token, local_path_token

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
async def python_bootstrap(
    python_bootstrap_subsystem: PythonBootstrapSubsystem, env_tgt: EnvironmentTarget
) -> PythonBootstrap:
    if env_tgt.val is not None:
        interpreter_search_paths = env_tgt.val[PythonInterpreterSearchPathsField].value
        interpreter_names = env_tgt.val[PythonBootstrapBinaryNamesField].value
        for opt in ("search_path", "names"):
            python_bootstrap_subsystem.error_if_environment_mechanism_ambiguity(opt)
    else:
        interpreter_search_paths = python_bootstrap_subsystem.search_path
        interpreter_names = python_bootstrap_subsystem.names

    has_standard_path_token, has_local_path_token = PythonBootstrap.contains_asdf_path_tokens(
        interpreter_search_paths
    )
    result = await Get(
        AsdfToolPathsResult,
        AsdfToolPathsRequest(
            tool_name="python",
            tool_description="Python interpreters",
            resolve_standard=has_standard_path_token,
            resolve_local=has_local_path_token,
            extra_env_var_names=PythonBootstrap.EXTRA_ENV_VAR_NAMES,
            paths_option_name="[python-bootstrap].search_path",
        ),
    )

    return PythonBootstrap(
        interpreter_names=interpreter_names,
        raw_interpreter_search_paths=interpreter_search_paths,
        environment=result.env,
        asdf_standard_tool_paths=result.standard_tool_paths,
        asdf_local_tool_paths=result.local_tool_paths,
    )


def rules():
    return (
        *collect_rules(),
        *asdf.rules(),
    )
