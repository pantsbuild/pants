# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.internals.selectors import MultiGet
from pants.engine.process import BinaryPath, BinaryPathRequest, BinaryPaths, BinaryPathTest
from pants.engine.rules import Get, collect_rules, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class PosixTools:
    """ `BinaryPath`s for standard Unix tools that may be used in internal shell scripts."""
    ln: BinaryPath


SEARCH_PATHS = ("/usr/bin", "/bin", "/usr/local/bin")


@rule(desc="Finding posix tools", level=LogLevel.DEBUG)
async def find_posix_tools() -> PosixTools:
    short_requests: dict[str, BinaryPathTest | None] = {
        "ln": None,
    }

    requests = [
        BinaryPathRequest(binary_name=name, search_path=SEARCH_PATHS, test=test)
        for name, test in short_requests.items()
    ]
    all_tool_paths = await MultiGet(
        Get(BinaryPaths, BinaryPathRequest, request) for request in requests
    )

    first_paths = {
        request.binary_name: paths.first_path_or_raise(
            request, rationale=f"use `{request.binary_name}` in internal shell scripts"
        )
        for request, paths in zip(requests, all_tool_paths)
    }

    return PosixTools(
        ln=first_paths["ln"],
    )


def rules():
    return collect_rules()
