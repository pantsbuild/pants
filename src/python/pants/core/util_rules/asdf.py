# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePath
from typing import Collection

from pants.base.build_environment import get_buildroot
from pants.base.build_root import BuildRoot
from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.selectors import Get
from pants.engine.rules import _uncacheable_rule, collect_rules
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


class AsdfPathString(str, Enum):
    STANDARD = "<ASDF>"
    LOCAL = "<ASDF_LOCAL>"

    @staticmethod
    def contains_strings(search_paths: Collection[str]) -> tuple[bool, bool]:
        return AsdfPathString.STANDARD in search_paths, AsdfPathString.LOCAL in search_paths

    def description(self, tool: str) -> str:
        if self is self.STANDARD:
            return softwrap(
                f"""
                all {tool} versions currently configured by ASDF `(asdf shell, ${{HOME}}/.tool-versions)`,
                with a fallback to all installed versions
                """
            )
        if self is self.LOCAL:
            return f"the ASDF {tool} with the version in `BUILD_ROOT/.tool-versions`"
        raise NotImplementedError(f"{self} has no description.")


@dataclass(frozen=True)
class AsdfToolPathsRequest:
    env_tgt: EnvironmentTarget
    tool_name: str
    tool_description: str
    resolve_standard: bool
    resolve_local: bool
    paths_option_name: str
    bin_relpath: str = "bin"


@dataclass(frozen=True)
class AsdfToolPathsResult:
    tool_name: str
    standard_tool_paths: tuple[str, ...] = ()
    local_tool_paths: tuple[str, ...] = ()

    @classmethod
    async def get_un_cachable_search_paths(
        cls,
        search_paths: Collection[str],
        env_tgt: EnvironmentTarget,
        tool_name: str,
        tool_description: str,
        paths_option_name: str,
        bin_relpath: str = "bin",
    ) -> AsdfToolPathsResult:
        resolve_standard, resolve_local = AsdfPathString.contains_strings(search_paths)

        if resolve_standard or resolve_local:
            # AsdfToolPathsResult is not cacheable, so only request it if absolutely necessary.
            return await Get(
                AsdfToolPathsResult,
                AsdfToolPathsRequest(
                    env_tgt=env_tgt,
                    tool_name=tool_name,
                    tool_description=tool_description,
                    resolve_standard=resolve_standard,
                    resolve_local=resolve_local,
                    paths_option_name=paths_option_name,
                    bin_relpath=bin_relpath,
                ),
            )
        return AsdfToolPathsResult(tool_name)


async def _resolve_asdf_tool_paths(
    env_tgt: EnvironmentTarget,
    tool_name: str,
    paths_option_name: str,
    tool_description: str,
    tool_env_name: str,
    bin_relpath: str,
    env: EnvironmentVars,
    local: bool,
) -> tuple[str, ...]:
    if not (isinstance(env_tgt.val, LocalEnvironmentTarget) or env_tgt.val is None):
        return ()

    asdf_dir = get_asdf_data_dir(env)
    if not asdf_dir:
        return ()

    asdf_dir = Path(asdf_dir)

    # Ignore ASDF if the tool's plugin isn't installed.
    asdf_tool_plugin = asdf_dir / "plugins" / tool_name
    if not asdf_tool_plugin.exists():
        return ()

    # Ignore ASDF if no versions of the tool have ever been installed (the installs folder is
    # missing).
    asdf_installs_dir = asdf_dir / "installs" / tool_name
    if not asdf_installs_dir.exists():
        return ()

    # Find all installed versions.
    asdf_installed_paths: list[str] = []
    for child in asdf_installs_dir.iterdir():
        # Aliases, and non-cpython installs (for Python) may have odd names.
        # Make sure that the entry is a subdirectory of the installs directory.
        if child.is_dir():
            # Make sure that the subdirectory has a bin directory.
            bin_dir = child.joinpath(bin_relpath)
            if bin_dir.exists():
                asdf_installed_paths.append(str(bin_dir))

    # Ignore ASDF if there are no installed versions.
    if not asdf_installed_paths:
        return ()

    asdf_paths: list[str] = []
    asdf_versions: dict[str, str] = {}
    tool_versions_file = None

    # Support "shell" based ASDF configuration
    tool_env_version = env.get(tool_env_name)
    if tool_env_version:
        asdf_versions.update([(v, tool_env_name) for v in re.split(r"\s+", tool_env_version)])

    # Target the local .tool-versions file.
    if local:
        tool_versions_file = Path(get_buildroot(), ".tool-versions")
        if not tool_versions_file.exists():
            logger.warning(
                softwrap(
                    f"""
                    No `.tool-versions` file found in the build root, but <ASDF_LOCAL> was set in
                    `{paths_option_name}`.
                    """
                )
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
        last_line_fields = None
        for line in tool_versions_lines:
            fields = re.split(r"\s+", line.strip())
            if not fields or fields[0] != tool_name:
                continue
            last_line_fields = fields
        if last_line_fields:
            for v in last_line_fields[1:]:
                if ":" in v:
                    key, _, value = v.partition(":")
                    if key.lower() == "path":
                        asdf_paths.append(value)
                    elif key.lower() == "ref":
                        asdf_versions[value] = str(tool_versions_file)
                    else:
                        logger.warning(
                            softwrap(
                                f"""
                                Unknown version format `{v}` from ASDF configured by
                                `{paths_option_name}`, ignoring. This
                                version will not be considered when determining which {tool_description}
                                to use. Please check that `{tool_versions_file}`
                                is accurate.
                            """
                            )
                        )
                elif v == "system":
                    logger.warning(
                        softwrap(
                            f"""
                            System path set by ASDF configured by `{paths_option_name}` is unsupported, ignoring.
                            This version will not be considered when determining which {tool_description} to use.
                            Please remove 'system' from `{tool_versions_file}` to disable this warning.
                            """
                        )
                    )
                else:
                    asdf_versions[v] = str(tool_versions_file)

    for version, source in asdf_versions.items():
        install_dir = asdf_installs_dir / version / bin_relpath
        if install_dir.exists():
            asdf_paths.append(str(install_dir))
        else:
            logger.warning(
                softwrap(
                    f"""
                    Trying to use ASDF version `{version}` configured by
                    `{paths_option_name}` but `{install_dir}` does not
                    exist. This version will not be considered when determining which {tool_description}
                    to use. Please check that `{source}` is accurate.
                    """
                )
            )

    # For non-local, if no paths have been defined, fallback to every version installed
    if not local and len(asdf_paths) == 0:
        # This could be appended to asdf_paths, but there isn't any reason to
        return tuple(asdf_installed_paths)
    else:
        return tuple(asdf_paths)


# TODO: This rule is marked uncacheable because it directly accsses the filesystem to examine ASDF configuration.
# See https://github.com/pantsbuild/pants/issues/10842 for potential future support for capturing from absolute
# paths that could allow this rule to be cached.
@_uncacheable_rule
async def resolve_asdf_tool_paths(
    request: AsdfToolPathsRequest, build_root: BuildRoot
) -> AsdfToolPathsResult:
    tool_env_name = f"ASDF_{request.tool_name.upper()}_VERSION"
    env_vars_to_request = [
        "ASDF_DIR",
        "ASDF_DATA_DIR",
        tool_env_name,
        "HOME",
    ]
    env = await Get(EnvironmentVars, EnvironmentVarsRequest(env_vars_to_request))

    standard_tool_paths: tuple[str, ...] = ()
    if request.resolve_standard:
        standard_tool_paths = await _resolve_asdf_tool_paths(
            env_tgt=request.env_tgt,
            tool_name=request.tool_name,
            paths_option_name=request.paths_option_name,
            tool_description=request.tool_description,
            tool_env_name=tool_env_name,
            bin_relpath=request.bin_relpath,
            env=env,
            local=False,
        )

    local_tool_paths: tuple[str, ...] = ()
    if request.resolve_local:
        local_tool_paths = await _resolve_asdf_tool_paths(
            env_tgt=request.env_tgt,
            tool_name=request.tool_name,
            paths_option_name=request.paths_option_name,
            tool_description=request.tool_description,
            tool_env_name=tool_env_name,
            bin_relpath=request.bin_relpath,
            env=env,
            local=True,
        )

    return AsdfToolPathsResult(
        tool_name=request.tool_name,
        standard_tool_paths=standard_tool_paths,
        local_tool_paths=local_tool_paths,
    )


def get_asdf_data_dir(env: EnvironmentVars) -> PurePath | None:
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


def rules():
    return collect_rules()
