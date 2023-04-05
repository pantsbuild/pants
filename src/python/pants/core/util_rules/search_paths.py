# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Iterable

from pants.base.build_environment import get_buildroot
from pants.core.util_rules.environments import EnvironmentTarget, LocalEnvironmentTarget
from pants.engine.collection import DeduplicatedCollection
from pants.engine.env_vars import EnvironmentVars
from pants.engine.rules import Rule, _uncacheable_rule, collect_rules, rule
from pants.option.option_types import StrListOption
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import help_text, softwrap

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidateSearchPathsRequest:
    env_tgt: EnvironmentTarget
    search_paths: tuple[str, ...]
    option_origin: str
    environment_key: str
    is_default: bool
    local_only: FrozenOrderedSet[str]


@dataclass(frozen=True)
class VersionManagerSearchPathsRequest:
    env_tgt: EnvironmentTarget
    root_dir: str | None
    tool_path: str
    option: str
    version_files: tuple[str, ...] = tuple()
    local_token: str | None = None


class VersionManagerSearchPaths(DeduplicatedCollection[str]):
    pass


@_uncacheable_rule
async def get_un_cachable_version_manager_paths(
    request: VersionManagerSearchPathsRequest,
) -> VersionManagerSearchPaths:
    """Inspects the directory of a version manager tool like pyenv or nvm to find installations."""
    if not (request.env_tgt.val is None or isinstance(request.env_tgt.val, LocalEnvironmentTarget)):
        return VersionManagerSearchPaths()

    manager_root_dir = request.root_dir
    if not manager_root_dir:
        return VersionManagerSearchPaths()
    root_path = Path(manager_root_dir)
    if not root_path.exists():
        return VersionManagerSearchPaths()

    tool_versions_path = root_path / request.tool_path
    if not tool_versions_path.is_dir():
        return VersionManagerSearchPaths()

    if request.local_token and request.version_files:
        local_version_files = [Path(get_buildroot(), file) for file in request.version_files]
        first_version_file = next((file for file in local_version_files if file.exists()), None)
        if not first_version_file:
            file_string = ", ".join(f"`{file}`" for file in local_version_files)
            no_file = (
                f"No {file_string}" if len(local_version_files) == 1 else f"None of {file_string}"
            )
            _logger.warning(
                softwrap(
                    f"""
                    {no_file} found in the build root,
                    but {request.local_token} was set in `{request.option}`.
                    """
                )
            )
            return VersionManagerSearchPaths()

        _logger.info(
            f"Reading {first_version_file} to determine desired version for {request.option}."
        )
        local_version = first_version_file.read_text().strip()
        path = Path(tool_versions_path, local_version, "bin")
        if path.is_dir():
            return VersionManagerSearchPaths([str(path)])
        return VersionManagerSearchPaths()

    versions_in_dir = (
        tool_versions_path / version / "bin" for version in sorted(tool_versions_path.iterdir())
    )
    return VersionManagerSearchPaths(
        str(version) for version in versions_in_dir if version.is_dir()
    )


class ValidatedSearchPaths(FrozenOrderedSet):
    """Search paths that are valid for the current target environment."""


@rule(level=LogLevel.DEBUG)
async def validate_search_paths(request: ValidateSearchPathsRequest) -> ValidatedSearchPaths:
    """Checks for special search path strings, and errors if any are invalid for the environment.

    This will return:
    * The search paths, unaltered, for local/undefined environments, OR
    * The search paths, with invalid tokens removed, if the provided value was unaltered from the
      default value in the options system.
    * The search paths unaltered, if the search paths are all valid tokens for this environment

    If the environment is non-local and there are invalid tokens for those environments, raise
    `ValueError`.
    """

    env = request.env_tgt.val
    search_paths = request.search_paths

    if env is None or isinstance(env, LocalEnvironmentTarget):
        return ValidatedSearchPaths(search_paths)

    if request.is_default:
        # Strip out the not-allowed special strings from search_paths.
        # An error will occur on the off chance the non-local environment expects local_only tokens,
        # but there's nothing we can do here to detect it.
        return ValidatedSearchPaths(path for path in search_paths if path not in request.local_only)

    any_not_allowed = set(search_paths) & request.local_only
    if any_not_allowed:
        env_type = type(env)
        raise ValueError(
            softwrap(
                f"`{request.option_origin}` is configured to use local discovery "
                f"tools, which do not work in {env_type.__name__} runtime environments. To fix "
                f"this, set the value of `{request.environment_key}` in the `{env.alias}` "
                f"defined at `{env.address}` to contain only hardcoded paths or the `<PATH>` "
                "special string."
            )
        )

    return ValidatedSearchPaths(search_paths)


class ExecutableSearchPathsOptionMixin:
    env_vars_used_by_options: ClassVar[tuple[str, ...]] = ("PATH",)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        if "PATH" not in cls.env_vars_used_by_options:
            raise ValueError(
                softwrap(
                    f"""
                    {ExecutableSearchPathsOptionMixin.__name__} depends on the PATH environment variable.

                    Please add it to the {cls.__name__}.env_vars_used_by_options.
                    """
                )
            )

    executable_search_paths_help: str
    _options_env: EnvironmentVars

    _executable_search_paths = StrListOption(
        default=["<PATH>"],
        help=lambda cls: help_text(
            f"""
            {cls.executable_search_paths_help}
            The special string `"<PATH>"` will expand to the contents of the PATH env var.
            """
        ),
        advanced=True,
        metavar="<binary-paths>",
    )

    @memoized_property
    def executable_search_path(self) -> tuple[str, ...]:
        def iter_path_entries():
            for entry in self._executable_search_paths:
                if entry == "<PATH>":
                    path = self._options_env.get("PATH")
                    if path:
                        yield from path.split(os.pathsep)
                else:
                    yield entry

        return tuple(OrderedSet(iter_path_entries()))


def rules() -> Iterable[Rule]:
    return collect_rules()
