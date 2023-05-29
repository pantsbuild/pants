# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import Iterable

from pants.backend.rust.subsystems.rust import RustSubsystem
from pants.core.util_rules.system_binaries import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.env_vars import EnvironmentVars, EnvironmentVarsRequest
from pants.engine.internals.native_engine import Digest
from pants.engine.internals.selectors import Get
from pants.engine.platform import Platform
from pants.engine.process import Process, ProcessCacheScope, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel


class RustupBinary(BinaryPath):
    """Path to the rustup binary used to select and gain access to Rust toolchains."""


@dataclass(frozen=True)
class RustToolchainProcess:
    binary: str
    args: tuple[str, ...]
    input_digest: Digest
    description: str = dataclasses.field(compare=False)
    level: LogLevel
    output_files: tuple[str, ...]
    output_directories: tuple[str, ...]
    platform: Platform | None
    cache_scope: ProcessCacheScope | None

    def __init__(
        self,
        binary: str,
        args: Iterable[str],
        input_digest: Digest,
        description: str,
        level: LogLevel = LogLevel.INFO,
        output_files: Iterable[str] | None = None,
        output_directories: Iterable[str] | None = None,
        platform: Platform | None = None,
        cache_scope: ProcessCacheScope | None = None,
    ):
        object.__setattr__(self, "binary", binary)
        object.__setattr__(self, "args", tuple(args))
        object.__setattr__(self, "input_digest", input_digest)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "output_files", tuple(output_files or ()))
        object.__setattr__(self, "output_directories", tuple(output_directories or ()))
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "cache_scope", cache_scope)


@rule
async def find_rustup(rust_subsystem: RustSubsystem) -> RustupBinary:
    env = await Get(EnvironmentVars, EnvironmentVarsRequest(["PATH"]))
    request = BinaryPathRequest(
        binary_name="rustup",
        search_path=rust_subsystem.rustup_search_paths(env),
        test=BinaryPathTest(args=["-V"]),
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, request)
    first_path = paths.first_path_or_raise(request, rationale="invoke rustup, rust installer")
    return RustupBinary(first_path.path, first_path.fingerprint)


@dataclass(frozen=True)
class RustBinaryPathRequest:
    binary: str


@rule
async def rust_binary_path(
    request: RustBinaryPathRequest, rustup: RustupBinary, rust_subsystem: RustSubsystem
) -> BinaryPath:
    which_result = await Get(
        ProcessResult,
        Process(
            argv=(rustup.path, "which", f"--toolchain={rust_subsystem.toolchain}", request.binary),
            description=f"Find path to Rust binary `{request.binary}` in toolchain `{rust_subsystem.toolchain}`",
        ),
    )
    binary_full_path = which_result.stdout.decode().strip()
    binary_path_request = BinaryPathRequest(
        binary_name=os.path.basename(binary_full_path),
        search_path=[os.path.dirname(binary_full_path)],
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, binary_path_request)
    binary_path = paths.first_path_or_raise(binary_path_request, rationale="invoke Rust")
    return binary_path


@rule
async def rust_toolchain_process(request: RustToolchainProcess) -> Process:
    binary_path = await Get(BinaryPath, RustBinaryPathRequest(request.binary))
    return Process(
        argv=[binary_path.path, *request.args],
        description=request.description,
        level=request.level,
        input_digest=request.input_digest,
        output_files=request.output_files,
        output_directories=request.output_directories,
        cache_scope=request.cache_scope or ProcessCacheScope.SUCCESSFUL,
    )


def rules():
    return collect_rules()
