# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.fs import EMPTY_SNAPSHOT, DigestContents, PathGlobs, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.util.collections import ensure_str_list
from pants.util.dirutil import find_nearest_ancestor_file
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
        config_snapshot = await Get(
            Snapshot,
            PathGlobs(
                globs=request.specified,
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"the option `{request.specified_option_name}`",
            ),
        )
        return ConfigFiles(config_snapshot)
    elif request.discovery:
        check_content_digest_contents = await Get(DigestContents, PathGlobs(request.check_content))
        valid_content_files = tuple(
            file_content.path
            for file_content in check_content_digest_contents
            if request.check_content[file_content.path] in file_content.content
        )
        config_snapshot = await Get(
            Snapshot, PathGlobs((*request.check_existence, *valid_content_files))
        )
    return ConfigFiles(config_snapshot)


class OrphanFilepathBehavior(Enum):
    IGNORE = "ignore"
    ERROR = "error"


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
    orphan_filepath_behavior: OrphanFilepathBehavior = OrphanFilepathBehavior.ERROR


@rule
async def gather_config_files_by_workspace_dir(
    request: GatherConfigFilesByDirectoriesRequest,
) -> GatheredConfigFilesByDirectories:
    """Gathers config files from the workspace and indexes them by the directories relative to
    them."""

    source_dirs = frozenset(os.path.dirname(path) for path in request.filepaths)
    source_dirs_with_ancestors = {"", *source_dirs}
    for source_dir in source_dirs:
        source_dir_parts = source_dir.split(os.path.sep)
        source_dir_parts.pop()
        while source_dir_parts:
            source_dirs_with_ancestors.add(os.path.sep.join(source_dir_parts))
            source_dir_parts.pop()

    config_file_globs = [
        os.path.join(dir, request.config_filename) for dir in source_dirs_with_ancestors
    ]
    config_files_snapshot = await Get(Snapshot, PathGlobs(config_file_globs))
    config_files_set = set(config_files_snapshot.files)

    source_dir_to_config_file: dict[str, str] = {}
    for source_dir in source_dirs:
        config_file = find_nearest_ancestor_file(
            config_files_set, source_dir, request.config_filename
        )

        if config_file:
            source_dir_to_config_file[source_dir] = config_file
        elif request.orphan_filepath_behavior == OrphanFilepathBehavior.ERROR:
            raise ValueError(
                softwrap(
                    f"""
                    No {request.tool_name} file (`{request.config_filename}`) found for
                    source directory '{source_dir}'.
                    """
                )
            )

    return GatheredConfigFilesByDirectories(
        request.config_filename, config_files_snapshot, FrozenDict(source_dir_to_config_file)
    )


def rules():
    return collect_rules()
