# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.engine.fs import (
    EMPTY_SNAPSHOT,
    DigestContents,
    GlobMatchErrorBehavior,
    PathGlobs,
    Paths,
    Snapshot,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
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
    """Resolve the specified config files if given, else look for candidate config files and warn if
    they exist but are not hooked up to Pants.

    Files in `check_existence` only need to exist, whereas files in `check_content` both must exist
    and contain the bytes snippet in the file.
    """

    specified: tuple[str, ...]
    check_existence: tuple[str, ...]
    check_content: FrozenDict[str, bytes]
    option_name: str

    def __init__(
        self,
        *,
        specified: str | Iterable[str] | None = None,
        option_name: str,
        check_existence: Iterable[str] = (),
        check_content: Mapping[str, bytes] = FrozenDict(),
    ) -> None:
        self.specified = tuple(ensure_str_list(specified or (), allow_single_str=True))
        self.check_existence = tuple(sorted(check_existence))
        self.check_content = FrozenDict(check_content)
        self.option_name = option_name


@rule(desc="Find config files", level=LogLevel.DEBUG)
async def warn_if_config_file_not_setup(request: ConfigFilesRequest) -> ConfigFiles:
    if request.specified:
        config_snapshot = await Get(
            Snapshot,
            PathGlobs(
                globs=request.specified,
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"the option `{request.option_name}`",
            ),
        )
        return ConfigFiles(config_snapshot)

    # Else, warn if there are config files but they're not hooked up to Pants.
    existence_paths, content_digest_contents = await MultiGet(
        Get(Paths, PathGlobs(request.check_existence)),
        Get(DigestContents, PathGlobs(request.check_content)),
    )
    discovered_config = sorted(
        {
            *existence_paths.files,
            *(
                file_content.path
                for file_content in content_digest_contents
                if request.check_content[file_content.path] in file_content.content
            ),
        }
    )
    if discovered_config:
        detected = (
            f"a relevant config file at {discovered_config[0]}"
            if len(discovered_config) == 1
            else f"relevant config files at {discovered_config}"
        )
        warning_prefix = f"The option `{request.option_name}` is not configured"
        logger.warning(
            f"{warning_prefix}, but Pants detected "
            f"{detected}. Did you mean to set the option `{request.option_name}`? Pants requires "
            f"that you explicitly set up config files for them to be used.\n\n"
            f"(If you do no want to use this config, you can ignore this warning by adding "
            f'`ignore_warnings = ["{warning_prefix}"]` to `pants.toml` in the `GLOBAL` '
            f"section.)"
        )

    return ConfigFiles(EMPTY_SNAPSHOT)


def rules():
    return collect_rules()
