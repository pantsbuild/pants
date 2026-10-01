# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.fs import EMPTY_SNAPSHOT, PathGlobs, Snapshot
from pants.engine.intrinsics import digest_to_snapshot, get_digest_contents
from pants.engine.rules import collect_rules, implicitly, rule
from pants.util.collections import ensure_str_list
from pants.util.dirutil import find_nearest_ancestor_file_by_priority_order
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigFiles:
    """Config files used by a tool run by Pants."""

    snapshot: Snapshot


@dataclass(frozen=True)
class ConfigFilesRequest:
    """Resolve the specified config files if given, else look for candidate config files if
    discovery is enabled.

    Files in `check_existence` only need to exist, whereas files in `check_content` both must exist
    and contain the bytes snippet in the file.
    """

    specified: tuple[str, ...]
    specified_option_name: str | None
    discovery: bool
    check_existence: tuple[str, ...]
    check_content: FrozenDict[str, bytes]

    def __init__(
        self,
        *,
        specified: str | Iterable[str] | None = None,
        specified_option_name: str | None = None,
        discovery: bool = False,
        check_existence: Iterable[str] = (),
        check_content: Mapping[str, bytes] = FrozenDict(),
    ) -> None:
        object.__setattr__(
            self, "specified", tuple(ensure_str_list(specified or (), allow_single_str=True))
        )
        object.__setattr__(self, "specified_option_name", specified_option_name)
        object.__setattr__(self, "discovery", discovery)
        object.__setattr__(self, "check_existence", tuple(sorted(check_existence)))
        object.__setattr__(self, "check_content", FrozenDict(check_content))


@rule(desc="Find config files", level=LogLevel.DEBUG)
async def find_config_file(request: ConfigFilesRequest) -> ConfigFiles:
    config_snapshot = EMPTY_SNAPSHOT
    if request.specified:
        config_snapshot = await digest_to_snapshot(
            **implicitly(
                PathGlobs(
                    globs=request.specified,
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin=f"the option `{request.specified_option_name}`",
                )
            )
        )
        return ConfigFiles(config_snapshot)
    elif request.discovery:
        check_content_digest_contents = await get_digest_contents(
            **implicitly(PathGlobs(request.check_content))
        )
        valid_content_files = tuple(
            file_content.path
            for file_content in check_content_digest_contents
            if request.check_content[file_content.path] in file_content.content
        )
        config_snapshot = await digest_to_snapshot(
            **implicitly(PathGlobs((*request.check_existence, *valid_content_files)))
        )
    return ConfigFiles(config_snapshot)


class OrphanFilepathConfigBehavior(Enum):
    IGNORE = "ignore"
    ERROR = "error"
    WARN = "warn"


@dataclass(frozen=True)
class GatheredPrioritizedConfigFilesByDirectories:
    config_filenames: tuple[str, ...]
    snapshot: Snapshot
    source_dir_to_config_file: FrozenDict[str, str]


@dataclass(frozen=True)
class GatherPrioritizedConfigFilesByDirectoriesRequest:
    """Like `GatherConfigFilesByDirectoriesRequest`, but with multiple valid config filename
    candidates, and a priority ordering of those filenames if multiple appear in a given directory.

    `content_marker_by_filename` maps from config filename to a byte-string marker required for the
    file to be considered a valid config (e.g. `pyproject.toml` might not have `[tool.mypy]`).
    """

    tool_name: str
    candidate_conf_filenames: tuple[str, ...]
    filepaths: tuple[str, ...]
    content_marker_by_filename: FrozenDict[str, bytes] = FrozenDict()
    orphan_filepath_behavior: OrphanFilepathConfigBehavior = OrphanFilepathConfigBehavior.ERROR


@rule
async def gather_prioritized_config_files_by_workspace_dir(
    request: GatherPrioritizedConfigFilesByDirectoriesRequest,
) -> GatheredPrioritizedConfigFilesByDirectories:
    """Gathers config files from the workspace and indexes them by the directories relative to
    them, preferring the nearest ancestor directory and then `candidate_conf_filenames` order."""

    source_dirs = frozenset(os.path.dirname(path) for path in request.filepaths)
    source_dirs_with_ancestors = {"", *source_dirs}
    for source_dir in source_dirs:
        ancestor = os.path.dirname(source_dir)
        while ancestor:
            source_dirs_with_ancestors.add(ancestor)
            ancestor = os.path.dirname(ancestor)

    candidate_globs = [
        os.path.join(dir, filename)
        for dir in source_dirs_with_ancestors
        for filename in request.candidate_conf_filenames
    ]
    candidate_digest_contents = await get_digest_contents(**implicitly(PathGlobs(candidate_globs)))
    valid_files = tuple(
        file_content.path
        for file_content in candidate_digest_contents
        if request.content_marker_by_filename.get(os.path.basename(file_content.path), b"")
        in file_content.content
    )

    config_files_snapshot = await digest_to_snapshot(**implicitly(PathGlobs(valid_files)))
    config_files_set = set(config_files_snapshot.files)
    source_dir_to_config_file: dict[str, str] = {}
    for source_dir in source_dirs:
        config_file = find_nearest_ancestor_file_by_priority_order(
            config_files_set, source_dir, request.candidate_conf_filenames
        )
        if config_file:
            source_dir_to_config_file[source_dir] = config_file
        else:
            filenames = " or ".join(f"`{name}`" for name in request.candidate_conf_filenames)
            msg = softwrap(
                f"""
                No {request.tool_name} file ({filenames}) found for
                source directory '{source_dir}'.
                """
            )
            if request.orphan_filepath_behavior == OrphanFilepathConfigBehavior.ERROR:
                raise ValueError(msg)
            elif request.orphan_filepath_behavior == OrphanFilepathConfigBehavior.WARN:
                logger.warning(msg)

    return GatheredPrioritizedConfigFilesByDirectories(
        request.candidate_conf_filenames,
        config_files_snapshot,
        FrozenDict(source_dir_to_config_file),
    )


@dataclass(frozen=True)
class GatheredConfigFilesByDirectories:
    config_filename: str
    snapshot: Snapshot
    source_dir_to_config_file: FrozenDict[str, str]


@dataclass(frozen=True)
class GatherConfigFilesByDirectoriesRequest:
    tool_name: str
    config_filename: str
    filepaths: tuple[str, ...]
    orphan_filepath_behavior: OrphanFilepathConfigBehavior = OrphanFilepathConfigBehavior.ERROR


@rule
async def gather_config_files_by_workspace_dir(
    request: GatherConfigFilesByDirectoriesRequest,
) -> GatheredConfigFilesByDirectories:
    """Gathers config files from the workspace and indexes them by the directories relative to
    them."""

    gathered = await gather_prioritized_config_files_by_workspace_dir(
        GatherPrioritizedConfigFilesByDirectoriesRequest(
            tool_name=request.tool_name,
            candidate_conf_filenames=(request.config_filename,),
            filepaths=request.filepaths,
            orphan_filepath_behavior=request.orphan_filepath_behavior,
        )
    )
    return GatheredConfigFilesByDirectories(
        request.config_filename, gathered.snapshot, gathered.source_dir_to_config_file
    )


def rules():
    return collect_rules()
