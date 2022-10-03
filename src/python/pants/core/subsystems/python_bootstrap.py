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
from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.rules import Get, _uncacheable_rule, collect_rules, rule
from pants.option.option_types import StrListOption
from pants.option.subsystem import Subsystem
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

    class EnvironmentAware(Subsystem.EnvironmentAware):
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

                For all runtime environment types:

                * `<PATH>`, the contents of the PATH env var

                When the environment is a `local_environment` target:

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


@dataclass(frozen=True)
class PythonBootstrap:
    interpreter_names: tuple[str, ...]
    interpreter_search_paths: tuple[str, ...]


@dataclass(frozen=True)
class _ExpandInterpreterSearchPathsRequest:
    interpreter_search_paths: Sequence[str]
    env_tgt: EnvironmentTarget


@dataclass(frozen=True)
class _PyEnvPathsRequest:
    env_tgt: EnvironmentTarget
    pyenv_local: bool = False


@dataclass(frozen=False)
class _SearchPaths:
    paths: tuple[str, ...]


@rule
async def _expand_interpreter_search_paths(
    request: _ExpandInterpreterSearchPathsRequest,
) -> _SearchPaths:

    interpreter_search_paths, env_tgt = (request.interpreter_search_paths, request.env_tgt)

    env = await Get(EnvironmentVars, EnvironmentVarsRequest(("PATH",)))

    has_asdf_standard_path_token, has_asdf_local_path_token = _contains_asdf_path_tokens(
        interpreter_search_paths
    )

    if has_asdf_standard_path_token or has_asdf_local_path_token:
        # `AsdfToolPathsResult` is uncacheable, so don't request it unless we actually need it.
        asdf_paths = await Get(
            AsdfToolPathsResult,
            AsdfToolPathsRequest(
                env_tgt=env_tgt,
                tool_name="python",
                tool_description="Python interpreters",
                resolve_standard=has_asdf_standard_path_token,
                resolve_local=has_asdf_local_path_token,
                paths_option_name="[python-bootstrap].search_path",
            ),
        )

        asdf_standard_tool_paths, asdf_local_tool_paths = (
            asdf_paths.standard_tool_paths,
            asdf_paths.local_tool_paths,
        )
    else:
        asdf_local_tool_paths, asdf_standard_tool_paths = (), ()

    special_strings = {
        "<PEXRC>": _get_pex_python_paths,
        "<PATH>": lambda: _get_environment_paths(env),
        "<ASDF>": lambda: asdf_standard_tool_paths,
        "<ASDF_LOCAL>": lambda: asdf_local_tool_paths,
    }

    expanded: list[str] = []
    from_pexrc = None
    for s in interpreter_search_paths:
        if s in special_strings:
            special_paths = special_strings[s]()
            if s == "<PEXRC>":
                from_pexrc = special_paths
            expanded.extend(special_paths)
        elif s == "<PYENV>" or s == "<PYENV_LOCAL>":
            paths = await Get(_SearchPaths, _PyEnvPathsRequest(env_tgt, s == "<PYENV_LOCAL>"))
            expanded.extend(paths.paths)
        else:
            expanded.append(s)
    # Some special-case logging to avoid misunderstandings.
    if from_pexrc and len(expanded) > len(from_pexrc):
        logger.info(
            softwrap(
                f"""
                pexrc interpreters requested and found, but other paths were also specified,
                so interpreters may not be restricted to the pexrc ones. Full search path is:

                {":".join(expanded)}
                """
            )
        )
    return _SearchPaths(tuple(expanded))


def _get_environment_paths(env: EnvironmentVars):
    """Returns a list of paths specified by the PATH env var."""
    pathstr = env.get("PATH")
    if pathstr:
        return pathstr.split(os.pathsep)
    return []


def _get_pex_python_paths():
    """Returns a list of paths to Python interpreters as defined in a pexrc file.

    These are provided by a PEX_PYTHON_PATH in either of '/etc/pexrc', '~/.pexrc'. PEX_PYTHON_PATH
    defines a colon-separated list of paths to interpreters that a pex can be built and run against.
    """
    ppp = Variables.from_rc().get("PEX_PYTHON_PATH")
    if ppp:
        return ppp.split(os.pathsep)
    else:
        return []


def _contains_asdf_path_tokens(interpreter_search_paths: Iterable[str]) -> tuple[bool, bool]:
    """Returns tuple of whether the path list contains standard or local ASDF path tokens."""
    standard_path_token = False
    local_path_token = False
    for interpreter_search_path in interpreter_search_paths:
        if interpreter_search_path == "<ASDF>":
            standard_path_token = True
        elif interpreter_search_path == "<ASDF_LOCAL>":
            local_path_token = True
    return standard_path_token, local_path_token


@_uncacheable_rule
async def _get_pyenv_paths(request: _PyEnvPathsRequest) -> _SearchPaths:
    """Returns a tuple of paths to Python interpreters managed by pyenv.

    :param `request.env_tgt`: The environment target -- if not referring to a local/no environment,
                                this will return an empty path.
    :param bool pyenv_local: If True, only use the interpreter specified by
                                '.python-version' file under `build_root`.
    """

    if not (request.env_tgt.val is None or isinstance(request.env_tgt.val, LocalEnvironmentTarget)):
        return _SearchPaths(())

    pyenv_local = request.pyenv_local
    env = await Get(EnvironmentVars, EnvironmentVarsRequest(("PYENV_ROOT", "HOME")))

    pyenv_root = _get_pyenv_root(env)
    if not pyenv_root:
        return _SearchPaths(())

    versions_dir = Path(pyenv_root, "versions")
    if not versions_dir.is_dir():
        return _SearchPaths(())

    if pyenv_local:
        local_version_file = Path(get_buildroot(), ".python-version")
        if not local_version_file.exists():
            logger.warning(
                softwrap(
                    """
                    No `.python-version` file found in the build root,
                    but <PYENV_LOCAL> was set in `[python-bootstrap].search_path`.
                    """
                )
            )
            return _SearchPaths(())

        local_version = local_version_file.read_text().strip()
        path = Path(versions_dir, local_version, "bin")
        if path.is_dir():
            return _SearchPaths((str(path),))
        return _SearchPaths(())

    paths = []
    for version in sorted(versions_dir.iterdir()):
        path = Path(versions_dir, version, "bin")
        if path.is_dir():
            paths.append(str(path))
    return _SearchPaths(tuple(paths))


def _get_pyenv_root(env: EnvironmentVars) -> str | None:
    """See https://github.com/pyenv/pyenv#environment-variables."""
    from_env = env.get("PYENV_ROOT")
    if from_env:
        return from_env
    home_from_env = env.get("HOME")
    if home_from_env:
        return os.path.join(home_from_env, ".pyenv")
    return None


def _preprocessed_interpreter_search_paths(
    env_tgt: EnvironmentTarget,
    _search_paths: Iterable[str],
    is_default: bool,
) -> tuple[str, ...]:
    """Checks for special search path strings, and errors if any are invalid for the environment.

    This will return:
    * The search paths, unaltered, for local/undefined environments, OR
    * The search paths, with invalid tokens removed, if the provided value was unaltered from the
      default value in the options system
      (see `PythonBootstrapSubsystem.EnvironmentAware.search_paths`)
    * The search paths unaltered, if the search paths are all valid tokens for this environment

    If the environment is non-local and there are invalid tokens for those environments, raise
    `ValueError`.
    """

    env = env_tgt.val
    search_paths = tuple(_search_paths)

    if env is None or isinstance(env, LocalEnvironmentTarget):
        return search_paths

    not_allowed = {"<PYENV>", "<PYENV_LOCAL>", "<ASDF>", "<ASDF_LOCAL>", "<PEXRC>"}

    if is_default:
        # Strip out the not-allowed special strings from search_paths.
        # An error will occur on the off chance the non-local environment expects pyenv
        # but there's nothing we can do here to detect it.
        return tuple(path for path in search_paths if path not in not_allowed)

    any_not_allowed = set(search_paths) & not_allowed
    if any_not_allowed:
        env_type = type(env)
        raise ValueError(
            softwrap(
                f"`[python-bootstrap].search_paths` is configured to use local Python discovery "
                f"tools, which do not work in {env_type.__name__} runtime environments. To fix "
                f"this, set the value of `python_bootstrap_search_path` in the `{env.alias}` "
                f"defined at `{env.address}` to contain only hardcoded paths or the `<PATH>` "
                "special string."
            )
        )

    return search_paths


@rule
async def python_bootstrap(
    python_bootstrap_subsystem: PythonBootstrapSubsystem.EnvironmentAware,
) -> PythonBootstrap:

    interpreter_search_paths = _preprocessed_interpreter_search_paths(
        python_bootstrap_subsystem.env_tgt,
        python_bootstrap_subsystem.search_path,
        python_bootstrap_subsystem._is_default("search_path"),
    )
    interpreter_names = python_bootstrap_subsystem.names

    expanded_paths = await Get(
        _SearchPaths,
        _ExpandInterpreterSearchPathsRequest(
            interpreter_search_paths,
            python_bootstrap_subsystem.env_tgt,
        ),
    )

    return PythonBootstrap(
        interpreter_names=interpreter_names,
        interpreter_search_paths=expanded_paths.paths,
    )


def rules():
    return (
        *collect_rules(),
        *asdf.rules(),
    )
