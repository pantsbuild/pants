# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import textwrap
from typing import List, Mapping, Optional, cast

import pytest

from pants.base.build_root import BuildRoot
from pants.core.goals.run import Run, RunFieldSet, RunRequest, RunSubsystem, run
from pants.core.util_rules.pants_environment import PantsEnvironment
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent, Workspace
from pants.engine.process import InteractiveProcess, InteractiveRunner
from pants.engine.target import Target, TargetRootsToFieldSets, TargetRootsToFieldSetsRequest
from pants.option.global_options import GlobalOptions
from pants.testutil.option_util import create_goal_subsystem, create_subsystem
from pants.testutil.rule_runner import MockConsole, MockGet, RuleRunner, run_rule_with_mocks


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner()


def create_mock_run_request(rule_runner: RuleRunner, program_text: bytes) -> RunRequest:
    digest = rule_runner.request(
        Digest,
        [CreateDigest([FileContent(path="program.py", content=program_text, is_executable=True)])],
    )
    return RunRequest(
        digest=digest,
        args=(os.path.join("{chroot}", "program.py"),),
        extra_env={"COLLIDING_ENV_VAR": ""},
    )


def single_target_run(
    rule_runner: RuleRunner,
    address: Address,
    console: MockConsole,
    *,
    program_text: bytes,
    extra_env_vars: Optional[List[str]] = None,
    pants_env: Optional[Mapping[str, str]] = None,
) -> Run:
    workspace = Workspace(rule_runner.scheduler)
    interactive_runner = InteractiveRunner(rule_runner.scheduler)

    class TestRunFieldSet(RunFieldSet):
        required_fields = ()

    class TestBinaryTarget(Target):
        alias = "binary"
        core_fields = ()
        help = "test binary target"

    target = TestBinaryTarget({}, address=address)
    field_set = TestRunFieldSet.create(target)

    res = run_rule_with_mocks(
        run,
        rule_args=[
            create_goal_subsystem(RunSubsystem, args=[], extra_env_vars=extra_env_vars or []),
            create_subsystem(GlobalOptions, pants_workdir=rule_runner.pants_workdir),
            console,
            interactive_runner,
            workspace,
            BuildRoot(),
            PantsEnvironment(env=pants_env),
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
    console = MockConsole(use_colors=False)
    program_text = b'#!/usr/bin/python\nprint("hello")'
    res = single_target_run(
        rule_runner,
        Address("some/addr"),
        console,
        program_text=program_text,
    )
    assert res.exit_code == 0


def test_env_vars(rule_runner: RuleRunner) -> None:
    console = MockConsole(use_colors=False)
    env_vars_output_path = os.path.join(rule_runner.build_root, "env.txt")
    program_text = textwrap.dedent(
        f"""\
        #!/usr/bin/python
        import os
        import sys
        with open("{env_vars_output_path}", "w") as fp:
            for k, v in os.environ.items():
                fp.write("{{}}={{}}\\n".format(k, v))
        """
    ).encode()

    res = single_target_run(
        rule_runner,
        Address("some/addr"),
        console,
        program_text=program_text,
        extra_env_vars=["FOO=bar"],
        pants_env={"BAZ": "from_pants_environment"},
    )
    assert res.exit_code == 0
    with open(env_vars_output_path) as fp:
        env_vars = list(fp)
    assert "FOO=bar\n" in env_vars

    # Test that we correctly validate that user-set env vars don't collide with ones that
    # Pants sets.
    with pytest.raises(ValueError) as excinfo:
        single_target_run(
            rule_runner,
            Address("some/addr"),
            console,
            program_text=program_text,
            extra_env_vars=["COLLIDING_ENV_VAR=dummy"],
        )
    assert "The following environment variables cannot be set" in str(excinfo.value)
    assert "COLLIDING_ENV_VAR" in str(excinfo.value)


def test_materialize_input_files(rule_runner: RuleRunner) -> None:
    program_text = b'#!/usr/bin/python\nprint("hello")'
    binary = create_mock_run_request(rule_runner, program_text)
    interactive_runner = InteractiveRunner(rule_runner.scheduler)
    process = InteractiveProcess(
        argv=("./program.py",),
        run_in_workspace=False,
        input_digest=binary.digest,
    )
    result = interactive_runner.run(process)
    assert result.exit_code == 0


def test_failed_run(rule_runner: RuleRunner) -> None:
    console = MockConsole(use_colors=False)
    program_text = b'#!/usr/bin/python\nraise RuntimeError("foo")'
    res = single_target_run(rule_runner, Address("some/addr"), console, program_text=program_text)
    assert res.exit_code == 1
