# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from pants.backend.adhoc.target_types import (
    SystemBinaryExtraSearchPathsField,
    SystemBinaryFingerprintArgsField,
    SystemBinaryFingerprintDependenciesField,
    SystemBinaryFingerprintPattern,
    SystemBinaryNameField,
)
from pants.build_graph.address import Address
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.adhoc_process_support import (
    ResolvedExecutionDependencies,
    ResolveExecutionDependenciesRequest,
)
from pants.core.util_rules.system_binaries import (
    SEARCH_PATHS,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import collect_rules, rule
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SystemBinaryFieldSet(RunFieldSet):
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    required_fields = (
        SystemBinaryNameField,
        SystemBinaryExtraSearchPathsField,
        SystemBinaryFingerprintPattern,
        SystemBinaryFingerprintArgsField,
        SystemBinaryFingerprintDependenciesField,
    )

    name: SystemBinaryNameField
    extra_search_paths: SystemBinaryExtraSearchPathsField
    fingerprint_pattern: SystemBinaryFingerprintPattern
    fingerprint_argv: SystemBinaryFingerprintArgsField
    fingerprint_dependencies: SystemBinaryFingerprintDependenciesField


async def _find_binary(
    address: Address,
    binary_name: str,
    extra_search_paths: Iterable[str],
    fingerprint_pattern: str | None,
    fingerprint_args: tuple[str, ...] | None,
    fingerprint_dependencies: tuple[str, ...] | None,
) -> BinaryPath:
    search_paths = tuple(extra_search_paths) + SEARCH_PATHS

    binaries = await Get(
        BinaryPaths,
        BinaryPathRequest(
            binary_name=binary_name,
            search_path=search_paths,
        ),
    )

    fingerprint_args = fingerprint_args or ()

    deps = await Get(
        ResolvedExecutionDependencies,
        ResolveExecutionDependenciesRequest(address, (), None, fingerprint_dependencies),
    )
    rds = deps.runnable_dependencies
    env: dict[str, str] = {}
    append_only_caches: Mapping[str, str] = {}
    immutable_input_digests: Mapping[str, Digest] = {}
    if rds:
        env = {"PATH": rds.path_component}
        env.update(**(rds.extra_env or {}))
        append_only_caches = rds.append_only_caches
        immutable_input_digests = rds.immutable_input_digests

    tests: tuple[FallibleProcessResult, ...] = await MultiGet(
        Get(
            FallibleProcessResult,
            Process(
                description=f"Testing candidate for `{binary_name}` at `{path.path}`",
                argv=(path.path,) + fingerprint_args,
                input_digest=deps.digest,
                env=env,
                append_only_caches=append_only_caches,
                immutable_input_digests=immutable_input_digests,
            ),
        )
        for path in binaries.paths
    )

    for test, binary in zip(tests, binaries.paths):
        if test.exit_code != 0:
            continue

        if fingerprint_pattern:
            fingerprint = test.stdout.decode().strip()
            match = re.match(fingerprint_pattern, fingerprint)
            if not match:
                continue

        return binary

    raise ValueError(
        f"Could not find a binary with name `{binary_name}`"
        + (
            ""
            if not fingerprint_pattern
            else f" with output matching `{fingerprint_pattern}` when run with arguments `{' '.join(fingerprint_args or ())}`"
        )
        + f". The following paths were searched: {', '.join(search_paths)}."
    )


@rule(level=LogLevel.DEBUG)
async def create_system_binary_run_request(field_set: SystemBinaryFieldSet) -> RunRequest:
    assert field_set.name.value is not None
    extra_search_paths = field_set.extra_search_paths.value or ()

    path = await _find_binary(
        field_set.address,
        field_set.name.value,
        extra_search_paths,
        field_set.fingerprint_pattern.value,
        field_set.fingerprint_argv.value,
        field_set.fingerprint_dependencies.value,
    )

    return RunRequest(
        digest=EMPTY_DIGEST,
        args=[path.path],
    )


def rules():
    return [
        *collect_rules(),
        *SystemBinaryFieldSet.rules(),
    ]
