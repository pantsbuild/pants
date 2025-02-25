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
from pants.backend.shell.util_rules.shell_command import (
    ShellCommandProcessFromTargetRequest,
    prepare_process_request_from_target,
)
from pants.core.goals.test import (
    TestDebugRequest,
    TestExtraEnv,
    TestFieldSet,
    TestRequest,
    TestResult,
    TestSubsystem,
)
from pants.core.util_rules.adhoc_process_support import (
    AdhocProcessRequest,
    FallibleAdhocProcessResult,
    prepare_adhoc_process,
)
from pants.core.util_rules.adhoc_process_support import rules as adhoc_process_support_rules
from pants.core.util_rules.adhoc_process_support import run_prepared_adhoc_process
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.internals.graph import resolve_target
from pants.engine.process import InteractiveProcess, ProcessCacheScope
from pants.engine.rules import collect_rules, implicitly, rule
from pants.engine.target import Target, WrappedTargetRequest
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
    wrapped_tgt = await resolve_target(
        WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
        **implicitly(),
    )

    shell_process = await prepare_process_request_from_target(
        ShellCommandProcessFromTargetRequest(wrapped_tgt.target), **implicitly()
    )

    shell_process = dataclasses.replace(
        shell_process,
        cache_scope=(
            ProcessCacheScope.PER_SESSION if test_subsystem.force else ProcessCacheScope.SUCCESSFUL
        ),
        env_vars=FrozenDict(
            {
                **test_extra_env.env,
                **shell_process.env_vars,
            }
        ),
    )

    results: list[FallibleAdhocProcessResult] = []
    for _ in range(test_subsystem.attempts_default):
        result = await run_prepared_adhoc_process(
            **implicitly({shell_process: AdhocProcessRequest})
        )  # noqa: PNT30: retry loop
        results.append(result)
        if result.process_result.exit_code == 0:
            break

    return TestResult.from_fallible_process_result(
        process_results=tuple(r.process_result for r in results),
        address=field_set.address,
        output_setting=test_subsystem.output,
    )


@rule(desc="Test with shell command (interactively)", level=LogLevel.DEBUG)
async def test_shell_command_interactively(
    batch: ShellTestRequest.Batch[TestShellCommandFieldSet, Any],
) -> TestDebugRequest:
    field_set = batch.single_element
    wrapped_tgt = await resolve_target(
        WrappedTargetRequest(field_set.address, description_of_origin="<infallible>"),
        **implicitly(),
    )

    prepared_request = await prepare_adhoc_process(
        **implicitly(ShellCommandProcessFromTargetRequest(wrapped_tgt.target))
    )

    # This is probably not strictly necessary given the use of `InteractiveProcess` but good to be correct in any event.
    shell_process = dataclasses.replace(
        prepared_request.process, cache_scope=ProcessCacheScope.PER_SESSION
    )

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
        *adhoc_process_support_rules(),
    )
