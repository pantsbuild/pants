# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.engine.fs import DigestContents, PathGlobs, Paths
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WarnConfigFilesNotSetupResult:
    pass


@frozen_after_init
@dataclass(unsafe_hash=True)
class WarnConfigFilesNotSetup:
    """Warn if any of the specified locations are found in the build root by suggesting that the
    user configure the corresponding option.

    Files in `check_existence` only need to exist, whereas files in `check_content` both must
    exist and contain the bytes snippet in the file.

    Use with `Get(WarnConfigFilesNotSetupResult, WarnConfigFilesNotSetupResult).
    """

    check_existence: tuple[str, ...]
    check_content: FrozenDict[str, bytes]
    option_name: str

    def __init__(
        self,
        *,
        option_name: str,
        check_existence: Iterable[str] = (),
        check_content: Mapping[str, bytes] = FrozenDict(),
    ) -> None:
        self.check_existence = tuple(sorted(check_existence))
        self.check_content = FrozenDict(check_content)
        self.option_name = option_name


@rule(desc="Check if config files not yet set up", level=LogLevel.DEBUG)
async def warn_if_config_file_not_setup(
    request: WarnConfigFilesNotSetup,
) -> WarnConfigFilesNotSetupResult:
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
    return WarnConfigFilesNotSetupResult()


def rules():
    return collect_rules()
