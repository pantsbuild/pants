# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import Optional, cast

import pytest

from pants.base.build_root import BuildRoot
from pants.core.goals.run import (
    Run,
    RunConsoleScriptRequest,
    RunFieldSet,
    RunRequest,
    RunSubsystem,
    find_console_script_to_run,
    run,
)
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent, Workspace
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPath,
    BinaryPathRequest,
    BinaryPaths,
    InteractiveProcess,
    InteractiveProcessResult,
)
from pants.engine.target import (
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    WrappedTarget,
)
from pants.option.global_options import GlobalOptions
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


def single_target_run(
    rule_runner: RuleRunner,
    *,
    address: Optional[Address] = None,
    console_script: Optional[str] = None,
    program_text: bytes,
) -> Run:
    assert address or console_script

    workspace = Workspace(rule_runner.scheduler, _enforce_effects=False)

    class TestRunFieldSet(RunFieldSet):
        required_fields = ()

    class TestBinaryTarget(Target):
        alias = "binary"
        core_fields = ()

    def mock_find_console_script_to_run(request: RunConsoleScriptRequest) -> RunRequest:
        assert request.console_script == console_script
        return create_mock_run_request(rule_runner, program_text)

    if address:
        target = TestBinaryTarget({}, address)
        field_sets = [TestRunFieldSet.create(target)]
    elif console_script:
        target = TestBinaryTarget({}, Address("not used"))
        field_sets = []

    with mock_console(rule_runner.options_bootstrapper) as (console, _):
        res = run_rule_with_mocks(
            run,
            rule_args=[
                create_goal_subsystem(RunSubsystem, args=[], console_script=console_script),
                create_subsystem(GlobalOptions, pants_workdir=rule_runner.pants_workdir),
                console,
                workspace,
                BuildRoot(),
                rule_runner.environment,
            ],
            mock_gets=[
                MockGet(
                    output_type=RunRequest,
                    input_type=RunConsoleScriptRequest,
                    mock=mock_find_console_script_to_run,
                ),
                MockGet(
                    output_type=TargetRootsToFieldSets,
                    input_type=TargetRootsToFieldSetsRequest,
                    mock=lambda _: TargetRootsToFieldSets({target: field_sets}),
                ),
                MockGet(
                    output_type=WrappedTarget,
                    input_type=Address,
                    mock=lambda _: WrappedTarget(target),
                ),
                MockGet(
                    output_type=RunRequest,
                    input_type=TestRunFieldSet,
                    mock=lambda _: create_mock_run_request(rule_runner, program_text),
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
    program_text = b'#!/usr/bin/python\nprint("hello")'
    res = single_target_run(
        rule_runner,
        address=Address("some/addr"),
        program_text=program_text,
    )
    assert res.exit_code == 0


def test_materialize_input_files(rule_runner: RuleRunner) -> None:
    program_text = b'#!/usr/bin/python\nprint("hello")'
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
    program_text = b'#!/usr/bin/python\nraise RuntimeError("foo")'
    res = single_target_run(rule_runner, address=Address("some/addr"), program_text=program_text)
    assert res.exit_code == 1


def test_console_script_run(rule_runner: RuleRunner) -> None:
    program_text = b'#!/usr/bin/python\nprint("hello")'
    res = single_target_run(
        rule_runner,
        console_script="script-name",
        program_text=program_text,
    )
    assert res.exit_code == 0


def run_find_console_script_to_run_rule(*paths: str) -> RunRequest:
    res = run_rule_with_mocks(
        find_console_script_to_run,
        rule_args=[
            RunConsoleScriptRequest("script-name"),
        ],
        mock_gets=[
            MockGet(
                output_type=BinaryPaths,
                input_type=BinaryPathRequest,
                mock=lambda _: BinaryPaths(
                    "script-name", [BinaryPath.fingerprinted(path, path.encode()) for path in paths]
                ),
            ),
        ],
    )
    return cast(RunRequest, res)


def test_find_console_script_to_run_not_found() -> None:
    with pytest.raises(BinaryNotFoundError, match="Cannot find `script-name` on "):
        # No paths => binary not found.
        run_find_console_script_to_run_rule()


def test_find_console_script_to_run_ok() -> None:
    path = "/.../bin/script-name"
    res = run_find_console_script_to_run_rule(path)
    assert res.args == (path,)
