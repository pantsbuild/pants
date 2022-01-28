# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from textwrap import dedent

from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix, Snapshot
from pants.engine.process import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
    Process,
    ProcessResult,
)
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.python import binaries as python_binaries
from pants.python.binaries import PythonBinary
from pants.util.logging import LogLevel


class GrepBinary(BinaryPath):
    pass

SEARCH_PATHS = ("/usr/bin", "/bin", "/usr/local/bin")


@rule(desc="Finding the `grep` binary", level=LogLevel.DEBUG)
async def find_grep() -> GrepBinary:
    request = BinaryPathRequest(
        binary_name="grep", search_path=SEARCH_PATHS, test=BinaryPathTest(args=["-V"])
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="use grep in internal shell scripts")
    return GrepBinary(first_path.path, first_path.fingerprint)


def rules():
    return collect_rules()
