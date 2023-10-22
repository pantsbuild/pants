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
from pants.core.goals.test import TestExtraEnv, TestFieldSet, TestRequest, TestResult, TestSubsystem
from pants.engine.internals.selectors import Get
from pants.engine.process import FallibleProcessResult, Process, ProcessCacheScope
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target, WrappedTarget, WrappedTargetRequest
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


class TestShellCommandFieldSet(TestFieldSet):
    required_fields = (
        ShellCommandCommandField,
        ShellCommandTestDependenciesField,
    )

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipShellCommandTestsField).value


class ShellTestRequest(TestRequest):
    tool_subsystem = ShellTestSubsystem
    field_set_type = TestShellCommandFieldSet


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

    shell_result = await Get(FallibleProcessResult, Process, shell_process)
    return TestResult.from_fallible_process_result(
        process_results=(shell_result,),
        address=field_set.address,
        output_setting=test_subsystem.output,
    )


def rules():
    return (
        *collect_rules(),
        *shell_command.rules(),
        *ShellTestRequest.rules(),
    )
