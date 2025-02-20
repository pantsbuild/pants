# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
from typing import Any

from pants.backend.shell.subsystems.shell_test_subsys import ShellTestSubsystem
from pants.backend.shell.target_types import (
    ShellCommandCommandField,
    ShellCommandTestDependenciesField,
    SkipShellCommandTestsField,
)
from pants.backend.shell.util_rules import shell_command
from pants.backend.shell.util_rules.shell_command import ShellCommandProcessFromTargetRequest
from pants.core.goals.test import (
    TestDebugRequest,
    TestExtraEnv,
    TestFieldSet,
    TestRequest,
    TestResult,
    TestSubsystem,
)
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.internals.selectors import Get
from pants.engine.process import (
    InteractiveProcess,
    Process,
    ProcessCacheScope,
    ProcessResultWithRetries,
    ProcessWithRetries,
)
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target, WrappedTarget, WrappedTargetRequest
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclasses.dataclass(frozen=True)
class TestShellCommandFieldSet(TestFieldSet):
    required_fields = (
        ShellCommandCommandField,
        ShellCommandTestDependenciesField,
    )

    environment: EnvironmentField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipShellCommandTestsField).value


class ShellTestRequest(TestRequest):
    tool_subsystem = ShellTestSubsystem
    field_set_type = TestShellCommandFieldSet
    supports_debug = True


@rule(desc="Test with shell command", level=LogLevel.DEBUG)
async def test_shell_command(
    batch: ShellTestRequest.Batch[TestShellCommandFieldSet, Any],
    test_subsystem: TestSubsystem,
    test_extra_env: TestExtraEnv,
) -> TestResult:
    field_set = batch.single_element
    wrapped_tgt = await Get(
        WrappedTarget,
        WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
    )

    shell_process = await Get(
        Process,
        ShellCommandProcessFromTargetRequest(wrapped_tgt.target),
    )

    shell_process = dataclasses.replace(
        shell_process,
        cache_scope=(
            ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
        ),
        env=FrozenDict(
            {
                **test_extra_env.env,
                **shell_process.env,
            }
        ),
    )

    shell_result = await Get(
        ProcessResultWithRetries, ProcessWithRetries(shell_process, test_subsystem.attempts_default)
    )
    return TestResult.from_fallible_process_result(
        process_results=shell_result.results,
        address=field_set.address,
        output_setting=test_subsystem.output,
    )


@rule(desc="Test with shell command (interactively)", level=LogLevel.DEBUG)
async def test_shell_command_interactively(
    batch: ShellTestRequest.Batch[TestShellCommandFieldSet, Any],
) -> TestDebugRequest:
    field_set = batch.single_element
    wrapped_tgt = await Get(
        WrappedTarget,
        WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
    )

    shell_process = await Get(
        Process,
        ShellCommandProcessFromTargetRequest(wrapped_tgt.target),
    )

    # This is probably not strictly necessary given the use of `InteractiveProcess` but good to be correct in any event.
    shell_process = dataclasses.replace(shell_process, cache_scope=ProcessCacheScope.PER_SESSION)

    return TestDebugRequest(
        InteractiveProcess.from_process(
            shell_process, forward_signals_to_process=False, restartable=True
        )
    )


def rules():
    return (
        *collect_rules(),
        *shell_command.rules(),
        *ShellTestRequest.rules(),
    )
