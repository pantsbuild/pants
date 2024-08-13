# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys
from typing import Iterable, Mapping, cast

import pytest
from _pytest.monkeypatch import MonkeyPatch

from pants.core.goals.run import (
    Run,
    RunDebugAdapterRequest,
    RunFieldSet,
    RunInSandboxBehavior,
    RunRequest,
    RunSubsystem,
    run,
)
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.core.util_rules.environments import EnvironmentNameRequest, EnvironmentTarget
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent, Workspace
from pants.engine.internals.specs_rules import (
    AmbiguousImplementationsException,
    TooManyTargetsException,
)
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.target import (
    FieldSet,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership
from pants.option.global_options import GlobalOptions, KeepSandboxes
from pants.testutil.option_util import create_goal_subsystem, create_subsystem
from pants.testutil.rule_runner import (
    MockEffect,
    MockGet,
    RuleRunner,
    mock_console,
    run_rule_with_mocks,
)
from pants.util.frozendict import FrozenDict


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


class TestRunFieldSet(RunFieldSet):
    required_fields = ()
    run_in_sandbox_behavior = RunInSandboxBehavior.NOT_SUPPORTED


class TestBinaryTarget(Target):
    alias = "binary"
    core_fields = ()


A_TARGET = TestBinaryTarget({}, Address("some/addr"))
A_FIELD_SET = TestRunFieldSet.create(A_TARGET)


def single_target_run(
    rule_runner: RuleRunner,
    monkeypatch: MonkeyPatch,
    *,
    program_text: bytes,
    targets_to_field_sets: Mapping[Target, Iterable[FieldSet]] = FrozenDict(
        {A_TARGET: (A_FIELD_SET,)}
    ),
) -> Run:
    workspace = Workspace(rule_runner.scheduler, _enforce_effects=False)

    def noop():
        pass

    monkeypatch.setattr("pants.engine.intrinsics.mark_nonrestartable", noop)
    with mock_console(rule_runner.options_bootstrapper) as (console, _):
        return run_rule_with_mocks(
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
                rule_runner.environment,
            ],
            mock_gets=[
                MockGet(
                    output_type=TargetRootsToFieldSets,
                    input_types=(TargetRootsToFieldSetsRequest,),
                    mock=lambda _: TargetRootsToFieldSets(targets_to_field_sets),
                ),
                rule_runner.do_not_use_mock(EnvironmentTarget, (EnvironmentNameRequest,)),
                MockGet(
                    output_type=RunRequest,
                    input_types=(RunFieldSet,),
                    mock=lambda _: create_mock_run_request(rule_runner, program_text),
                ),
                MockGet(
                    output_type=RunDebugAdapterRequest,
                    input_types=(RunFieldSet,),
                    mock=lambda _: create_mock_run_request(rule_runner, program_text),
                ),
                MockEffect(
                    output_type=InteractiveProcessResult,
                    input_types=(InteractiveProcess,),
                    mock=rule_runner.run_interactive_process,
                ),
            ],
            union_membership=UnionMembership(
                {
                    RunFieldSet: [TestRunFieldSet],
                    RunDebugAdapterRequest: [TestRunFieldSet],
                },
            ),
        )


def test_normal_run(rule_runner: RuleRunner, monkeypatch: MonkeyPatch) -> None:
    program_text = f'#!{sys.executable}\nprint("hello")'.encode()
    res = single_target_run(
        rule_runner,
        monkeypatch,
        program_text=program_text,
    )
    assert res.exit_code == 0


def test_materialize_input_files(rule_runner: RuleRunner, monkeypatch: MonkeyPatch) -> None:
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


def test_failed_run(rule_runner: RuleRunner, monkeypatch: MonkeyPatch) -> None:
    program_text = f'#!{sys.executable}\nraise RuntimeError("foo")'.encode()
    res = single_target_run(rule_runner, monkeypatch, program_text=program_text)
    assert res.exit_code == 1


def test_multi_target_error(rule_runner: RuleRunner, monkeypatch: MonkeyPatch) -> None:
    program_text = f'#!{sys.executable}\nprint("hello")'.encode()
    t1 = TestBinaryTarget({}, Address("some/addr"))
    t1_fs = TestRunFieldSet.create(t1)
    t2 = TestBinaryTarget({}, Address("some/other_addr"))
    t2_fs = TestRunFieldSet.create(t2)
    with pytest.raises(TooManyTargetsException):
        single_target_run(
            rule_runner,
            monkeypatch,
            program_text=program_text,
            targets_to_field_sets={t1: [t1_fs], t2: [t2_fs]},
        )


def test_multi_field_set_error(rule_runner: RuleRunner, monkeypatch: MonkeyPatch) -> None:
    program_text = f'#!{sys.executable}\nprint("hello")'.encode()
    target = TestBinaryTarget({}, Address("some/addr"))
    fs1 = TestRunFieldSet.create(target)
    fs2 = TestRunFieldSet.create(target)
    with pytest.raises(AmbiguousImplementationsException):
        single_target_run(
            rule_runner,
            monkeypatch,
            program_text=program_text,
            targets_to_field_sets={target: [fs1, fs2]},
        )
