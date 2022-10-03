# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.subsystems.golang import GolangSubsystem
from pants.core.util_rules.system_binaries import (
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule


@dataclass(frozen=True)
class CGoBinaryPathRequest(EngineAwareParameter):
    binary_name: str
    binary_path_test: BinaryPathTest | None

    def debug_hint(self) -> str | None:
        return self.binary_name


@rule
async def find_cgo_binary_path(
    request: CGoBinaryPathRequest, golang_env_aware: GolangSubsystem.EnvironmentAware
) -> BinaryPath:
    path_request = BinaryPathRequest(
        binary_name=request.binary_name,
        search_path=golang_env_aware.cgo_tool_search_paths,
        test=request.binary_path_test,
    )
    paths = await Get(BinaryPaths, BinaryPathRequest, path_request)
    first_path = paths.first_path_or_raise(
        path_request, rationale=f"find the `{request.binary_name}` tool required by CGo"
    )
    return first_path


def rules():
    return collect_rules()
