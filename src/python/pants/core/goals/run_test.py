# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import cast

from pants.base.build_root import BuildRoot
from pants.base.specs import SingleAddress
from pants.core.goals.binary import BinaryConfiguration, CreatedBinary
from pants.core.goals.run import Run, RunOptions, run
from pants.engine.addresses import Address
from pants.engine.fs import Digest, FileContent, InputFilesContent, Workspace
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.target import RegisteredTargetTypes, Target, TargetsWithOrigins, TargetWithOrigin
from pants.engine.unions import UnionMembership
from pants.option.global_options import GlobalOptions
from pants.testutil.engine.util import (
    MockConsole,
    MockGet,
    create_goal_subsystem,
    create_subsystem,
    run_rule,
)
from pants.testutil.test_base import TestBase


class RunTest(TestBase):
    def create_mock_binary(self, program_text: bytes) -> CreatedBinary:
        input_files_content = InputFilesContent(
            (FileContent(path="program.py", content=program_text, is_executable=True),)
        )
        digest = self.request_single_product(Digest, input_files_content)
        return CreatedBinary(binary_name="program.py", digest=digest,)

    def single_target_run(
        self, *, console: MockConsole, program_text: bytes, address_spec: str,
    ) -> Run:
        workspace = Workspace(self.scheduler)
        interactive_runner = InteractiveRunner(self.scheduler)

        class TestBinaryConfiguration(BinaryConfiguration):
            required_fields = ()

        class TestBinaryTarget(Target):
            alias = "binary"
            core_fields = ()

        address = Address.parse(address_spec)
        origin = SingleAddress(address.spec_path, address.target_name)
        res = run_rule(
            run,
            rule_args=[
                console,
                workspace,
                interactive_runner,
                BuildRoot(),
                TargetsWithOrigins(
                    [
                        TargetWithOrigin(
                            target=TestBinaryTarget(unhydrated_values={}, address=address),
                            origin=origin,
                        )
                    ]
                ),
                create_goal_subsystem(RunOptions, args=[]),
                create_subsystem(GlobalOptions, pants_workdir=self.pants_workdir),
                UnionMembership({BinaryConfiguration: [TestBinaryConfiguration]}),
                RegisteredTargetTypes.create([TestBinaryTarget]),
            ],
            mock_gets=[
                MockGet(
                    product_type=CreatedBinary,
                    subject_type=TestBinaryConfiguration,
                    mock=lambda _: self.create_mock_binary(program_text),
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
        self.assertEqual(res.exit_code, 0)
        self.assertEqual(
            console.stdout.getvalue(),
            "Running target: some/addr:addr\nsome/addr:addr ran successfully.\n",
        )
        self.assertEqual(console.stderr.getvalue(), "")

    def test_materialize_input_files(self) -> None:
        program_text = b'#!/usr/bin/python\nprint("hello")'
        binary = self.create_mock_binary(program_text)
        interactive_runner = InteractiveRunner(self.scheduler)
        request = InteractiveProcessRequest(
            argv=("./program.py",), run_in_workspace=False, input_files=binary.digest,
        )
        result = interactive_runner.run_local_interactive_process(request)
        self.assertEqual(result.process_exit_code, 0)

    def test_no_input_files_in_workspace(self) -> None:
        program_text = b'#!/usr/bin/python\nprint("hello")'
        binary = self.create_mock_binary(program_text)
        with self.assertRaises(ValueError):
            InteractiveProcessRequest(
                argv=("/usr/bin/python",), run_in_workspace=True, input_files=binary.digest
            )

    def test_failed_run(self) -> None:
        console = MockConsole(use_colors=False)
        program_text = b'#!/usr/bin/python\nraise RuntimeError("foo")'
        res = self.single_target_run(
            console=console, program_text=program_text, address_spec="some/addr"
        )
        self.assertEqual(res.exit_code, 1)
        self.assertEqual(console.stdout.getvalue(), "Running target: some/addr:addr\n")
        self.assertEqual(console.stderr.getvalue(), "some/addr:addr failed with code 1!\n")
