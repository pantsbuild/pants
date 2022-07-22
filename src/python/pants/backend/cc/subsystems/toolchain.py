# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable

from pants.core.util_rules.system_binaries import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CCToolchain:
    """A configured C/C++ toolchain for the current platform."""

    c: str
    cpp: str
    ld: str


# TODO: Just hardcoding this for now - need to figure out a good way to get clang (path), gcc (path), or arm-gcc (download)
@rule(desc="Setup the CC Toolchain", level=LogLevel.DEBUG)
async def setup_gcc_toolchain() -> CCToolchain:
    default_search_paths = ["/usr/local/bin", "/usr/bin", "/bin"]
    cc_paths = await Get(
        BinaryPaths,
        BinaryPathRequest(
            binary_name="gcc",
            search_path=default_search_paths,
            test=BinaryPathTest(args=["-v"]),
        ),
    )
    logger.error(cc_paths)
    if not cc_paths or not cc_paths.first_path:
        raise BinaryNotFoundError(f"Could not find 'gcc' in any of {default_search_paths}.")

    return CCToolchain(c=cc_paths.first_path.path, cpp="/usr/bin/g++", ld="/usr/bin/ld")


def rules() -> Iterable[Rule | UnionRule]:
    return collect_rules()
