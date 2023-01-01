# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.fs import EMPTY_SNAPSHOT, DigestContents, PathGlobs, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.util.collections import ensure_str_list
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigFiles:
    """Config files used by a tool run by Pants."""

    snapshot: Snapshot


@frozen_after_init
@dataclass(unsafe_hash=True)
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
        self.specified = tuple(ensure_str_list(specified or (), allow_single_str=True))
        self.specified_option_name = specified_option_name
        self.discovery = discovery
        self.check_existence = tuple(sorted(check_existence))
        self.check_content = FrozenDict(check_content)


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


def rules():
    return collect_rules()
