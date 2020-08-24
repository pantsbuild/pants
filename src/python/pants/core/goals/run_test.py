# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from typing import cast

from pants.base.build_root import BuildRoot
from pants.base.specs import AddressLiteralSpec
from pants.core.goals.run import Run, RunFieldSet, RunRequest, RunSubsystem, run
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent, Workspace
from pants.engine.process import InteractiveProcess, InteractiveRunner
from pants.engine.target import (
    Target,
    TargetsToValidFieldSets,
    TargetsToValidFieldSetsRequest,
    TargetWithOrigin,
)
from pants.option.global_options import GlobalOptions
from pants.testutil.engine_util import MockConsole, MockGet, run_rule
from pants.testutil.option_util import create_goal_subsystem, create_subsystem
from pants.testutil.test_base import TestBase


class RunTest(TestBase):
    def create_mock_run_request(self, program_text: bytes) -> RunRequest:
        digest = self.request_product(
            Digest,
            [
                CreateDigest(
                    [FileContent(path="program.py", content=program_text, is_executable=True)]
                )
            ],
        )
        return RunRequest(digest=digest, args=(os.path.join("{chroot}", "program.py"),))

    def single_target_run(
        self, *, console: MockConsole, program_text: bytes, address_spec: str,
    ) -> Run:
        workspace = Workspace(self.scheduler)
        interactive_runner = InteractiveRunner(self.scheduler)

        class TestRunFieldSet(RunFieldSet):
            required_fields = ()

        class TestBinaryTarget(Target):
            alias = "binary"
            core_fields = ()

        address = Address.parse(address_spec)
        target = TestBinaryTarget({}, address=address)
        target_with_origin = TargetWithOrigin(
            target, AddressLiteralSpec(address.spec_path, address.target_name)
        )
        field_set = TestRunFieldSet.create(target)

        res = run_rule(
            run,
            rule_args=[
                create_goal_subsystem(RunSubsystem, args=[]),
                create_subsystem(GlobalOptions, pants_workdir=self.pants_workdir),
                console,
                interactive_runner,
                workspace,
                BuildRoot(),
            ],
            mock_gets=[
                MockGet(
                    product_type=TargetsToValidFieldSets,
                    subject_type=TargetsToValidFieldSetsRequest,
                    mock=lambda _: TargetsToValidFieldSets({target_with_origin: [field_set]}),
                ),
                MockGet(
                    product_type=RunRequest,
                    subject_type=TestRunFieldSet,
                    mock=lambda _: self.create_mock_run_request(program_text),
                ),
            ],
        )
        return cast(Run, res)

    def test_normal_run(self) -> None:
        console = MockConsole(use_colors=False)
        program_text = b'#!/usr/bin/python\nprint("hello")'
        res = self.single_target_run(
            console=console, program_text=program_text, address_spec="some/addr",
        )
        assert res.exit_code == 0

    def test_materialize_input_files(self) -> None:
        program_text = b'#!/usr/bin/python\nprint("hello")'
        binary = self.create_mock_run_request(program_text)
        interactive_runner = InteractiveRunner(self.scheduler)
        process = InteractiveProcess(
            argv=("./program.py",), run_in_workspace=False, input_digest=binary.digest,
        )
        result = interactive_runner.run(process)
        assert result.exit_code == 0

    def test_failed_run(self) -> None:
        console = MockConsole(use_colors=False)
        program_text = b'#!/usr/bin/python\nraise RuntimeError("foo")'
        res = self.single_target_run(
            console=console, program_text=program_text, address_spec="some/addr"
        )
        assert res.exit_code == 1
