# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import sys
from typing import cast

import pytest

from pants.base.build_root import BuildRoot
from pants.core.goals.run import (
    Run,
    RunDebugAdapterRequest,
    RunFieldSet,
    RunRequest,
    RunSubsystem,
    run,
)
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent, Workspace
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.target import (
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.option.global_options import GlobalOptions, KeepSandboxes
from pants.testutil.option_util import create_goal_subsystem, create_subsystem
from pants.testutil.rule_runner import (
    MockEffect,
    MockGet,
    RuleRunner,
    mock_console,
    run_rule_with_mocks,
)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def create_mock_run_request(rule_runner: RuleRunner, program_text: bytes) -> RunRequest:
    digest = rule_runner.request(
        Digest,
        [CreateDigest([FileContent(path="program.py", content=program_text, is_executable=True)])],
    )
    return RunRequest(digest=digest, args=(os.path.join("{chroot}", "program.py"),))


def create_mock_run_debug_adapter_request(
    rule_runner: RuleRunner, program_text: bytes
) -> RunDebugAdapterRequest:
    return cast(RunDebugAdapterRequest, create_mock_run_request(rule_runner, program_text))


def single_target_run(
    rule_runner: RuleRunner,
    address: Address,
    *,
    program_text: bytes,
) -> Run:
    workspace = Workspace(rule_runner.scheduler, _enforce_effects=False)

    class TestRunFieldSet(RunFieldSet):
        required_fields = ()

    class TestBinaryTarget(Target):
        alias = "binary"
        core_fields = ()

    target = TestBinaryTarget({}, address)
    field_set = TestRunFieldSet.create(target)

    with mock_console(rule_runner.options_bootstrapper) as (console, _):
        res = run_rule_with_mocks(
            run,
            rule_args=[
                create_goal_subsystem(RunSubsystem, args=[], cleanup=True, debug_adapter=False),
                create_subsystem(
                    DebugAdapterSubsystem,
                    host="127.0.0.1",
                    port="5678",
                ),
                create_subsystem(
                    GlobalOptions,
                    pants_workdir=rule_runner.pants_workdir,
                    keep_sandboxes=KeepSandboxes.never,
                ),
                workspace,
                BuildRoot(),
                rule_runner.environment,
            ],
            mock_gets=[
                MockGet(
                    output_type=TargetRootsToFieldSets,
                    input_type=TargetRootsToFieldSetsRequest,
                    mock=lambda _: TargetRootsToFieldSets({target: [field_set]}),
                ),
                MockGet(
                    output_type=WrappedTarget,
                    input_type=WrappedTargetRequest,
                    mock=lambda _: WrappedTarget(target),
                ),
                MockGet(
                    output_type=RunRequest,
                    input_type=TestRunFieldSet,
                    mock=lambda _: create_mock_run_request(rule_runner, program_text),
                ),
                MockGet(
                    output_type=RunDebugAdapterRequest,
                    input_type=TestRunFieldSet,
                    mock=lambda _: create_mock_run_debug_adapter_request(rule_runner, program_text),
                ),
                MockEffect(
                    output_type=InteractiveProcessResult,
                    input_type=InteractiveProcess,
                    mock=rule_runner.run_interactive_process,
                ),
            ],
        )
        return cast(Run, res)


def test_normal_run(rule_runner: RuleRunner) -> None:
    program_text = f'#!{sys.executable}\nprint("hello")'.encode()
    res = single_target_run(
        rule_runner,
        Address("some/addr"),
        program_text=program_text,
    )
    assert res.exit_code == 0


def test_materialize_input_files(rule_runner: RuleRunner) -> None:
    program_text = f'#!{sys.executable}\nprint("hello")'.encode()
    binary = create_mock_run_request(rule_runner, program_text)
    with mock_console(rule_runner.options_bootstrapper):
        result = rule_runner.run_interactive_process(
            InteractiveProcess(
                argv=("./program.py",),
                run_in_workspace=False,
                input_digest=binary.digest,
            )
        )
    assert result.exit_code == 0


def test_failed_run(rule_runner: RuleRunner) -> None:
    program_text = f'#!{sys.executable}\nraise RuntimeError("foo")'.encode()
    res = single_target_run(rule_runner, Address("some/addr"), program_text=program_text)
    assert res.exit_code == 1
