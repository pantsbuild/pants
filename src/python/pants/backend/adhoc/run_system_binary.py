# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable

from pants.backend.adhoc.target_types import (
    SystemBinaryExtraSearchPathsField,
    SystemBinaryFingerprintArgsField,
    SystemBinaryFingerprintPattern,
    SystemBinaryNameField,
)
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior, RunRequest
from pants.core.util_rules.system_binaries import (
    SEARCH_PATHS,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    BinaryPathTest,
)
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule, rule_helper
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
    )

    name: SystemBinaryNameField
    extra_search_paths: SystemBinaryExtraSearchPathsField
    fingerprint_pattern: SystemBinaryFingerprintPattern
    fingerprint_argv: SystemBinaryFingerprintArgsField


@rule_helper
async def _find_binary(
    binary_name: str,
    extra_search_paths: Iterable[str],
    fingerprint_pattern: str | None,
    fingerprint_args: tuple[str, ...] | None,
) -> BinaryPath:

    test = (
        BinaryPathTest(fingerprint_args or (), fingerprint_stdout=False)
        if fingerprint_pattern
        else None
    )

    search_paths = tuple(extra_search_paths) + SEARCH_PATHS

    binaries = await Get(
        BinaryPaths,
        BinaryPathRequest(
            binary_name=binary_name,
            search_path=search_paths,
            test=test,
        ),
    )

    for binary in binaries.paths:
        if fingerprint_pattern:
            fingerprint = binary.fingerprint.strip()
            match = re.match(fingerprint_pattern, fingerprint)
            if not match:
                continue

        return binary

    raise ValueError(
        f"Could not find a binary with `{binary_name}`"
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
        field_set.name.value,
        extra_search_paths,
        field_set.fingerprint_pattern.value,
        field_set.fingerprint_argv.value,
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
