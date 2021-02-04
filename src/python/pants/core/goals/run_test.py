# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import cast

import pytest

from pants.base.build_root import BuildRoot
from pants.core.goals.run import Run, RunFieldSet, RunRequest, RunSubsystem, run
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent, Workspace
from pants.engine.process import InteractiveProcess, InteractiveRunner
from pants.engine.target import Target, TargetRootsToFieldSets, TargetRootsToFieldSetsRequest
from pants.option.global_options import GlobalOptions
from pants.testutil.option_util import create_goal_subsystem, create_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks


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
    address: Address,
    *,
    program_text: bytes,
) -> Run:
    workspace = Workspace(rule_runner.scheduler)
    interactive_runner = InteractiveRunner(rule_runner.scheduler)

    class TestRunFieldSet(RunFieldSet):
        required_fields = ()

    class TestBinaryTarget(Target):
        alias = "binary"
        core_fields = ()

    target = TestBinaryTarget({}, address=address)
    field_set = TestRunFieldSet.create(target)

    with mock_console(rule_runner.options_bootstrapper) as (console, _):
        res = run_rule_with_mocks(
            run,
            rule_args=[
                create_goal_subsystem(RunSubsystem, args=[]),
                create_subsystem(GlobalOptions, pants_workdir=rule_runner.pants_workdir),
                console,
                interactive_runner,
                workspace,
                BuildRoot(),
            ],
            mock_gets=[
                MockGet(
                    output_type=TargetRootsToFieldSets,
                    input_type=TargetRootsToFieldSetsRequest,
                    mock=lambda _: TargetRootsToFieldSets({target: [field_set]}),
                ),
                MockGet(
                    output_type=RunRequest,
                    input_type=TestRunFieldSet,
                    mock=lambda _: create_mock_run_request(rule_runner, program_text),
                ),
            ],
        )
        return cast(Run, res)


def test_normal_run(rule_runner: RuleRunner) -> None:
    program_text = b'#!/usr/bin/python\nprint("hello")'
    res = single_target_run(
        rule_runner,
        Address("some/addr"),
        program_text=program_text,
    )
    assert res.exit_code == 0


def test_materialize_input_files(rule_runner: RuleRunner) -> None:
    program_text = b'#!/usr/bin/python\nprint("hello")'
    binary = create_mock_run_request(rule_runner, program_text)
    with mock_console(rule_runner.options_bootstrapper) as (_, _):
        interactive_runner = InteractiveRunner(rule_runner.scheduler)
        process = InteractiveProcess(
            argv=("./program.py",),
            run_in_workspace=False,
            input_digest=binary.digest,
        )
        result = interactive_runner.run(process)
    assert result.exit_code == 0


def test_failed_run(rule_runner: RuleRunner) -> None:
    program_text = b'#!/usr/bin/python\nraise RuntimeError("foo")'
    res = single_target_run(rule_runner, Address("some/addr"), program_text=program_text)
    assert res.exit_code == 1
