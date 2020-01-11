# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.fs import Digest, FileContent, InputFilesContent, Workspace
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.rules.core import run
from pants.rules.core.binary import CreatedBinary
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.goal_rule_test_base import GoalRuleTestBase


class RunTest(GoalRuleTestBase):
  goal_cls = run.Run

  def create_mock_binary(self, program_text: bytes) -> CreatedBinary:
    input_files_content = InputFilesContent((
      FileContent(path='program.py', content=program_text, is_executable=True),
    ))
    digest = self.request_single_product(Digest, input_files_content)
    return CreatedBinary(
      binary_name='program.py',
      digest=digest,
    )

  def single_target_run(self, *, console: MockConsole, program_text: bytes, spec: str):
    workspace = Workspace(self.scheduler)
    interactive_runner = InteractiveRunner(self.scheduler)
    address = Address.parse(spec)
    bfa = BuildFileAddress(
      build_file=None,
      target_name=address.target_name,
      rel_path=f'{address.spec_path}/BUILD'
    )
    BuildRoot().path = self.build_root
    res = run_rule(
      run.run,
      rule_args=[console, workspace, interactive_runner, BuildRoot(), bfa],
      mock_gets=[
        MockGet(
          product_type=CreatedBinary,
          subject_type=Address,
          mock=lambda _: self.create_mock_binary(program_text)
        ),
      ],
    )
    return res

  def test_normal_run(self) -> None:
    console = MockConsole(use_colors=False)
    program_text = b'#!/usr/bin/python\nprint("hello")'
    res = self.single_target_run(
      console=console,
      program_text=program_text,
      spec='some/addr'
    )
    self.assertEqual(res.exit_code, 0)
    self.assertEquals(console.stdout.getvalue(), "Running target: some/addr:addr\nsome/addr:addr ran successfully.\n")
    self.assertEquals(console.stderr.getvalue(), "")

  def test_materialize_input_files(self) -> None:
    program_text = b'#!/usr/bin/python\nprint("hello")'
    binary = self.create_mock_binary(program_text)
    interactive_runner = InteractiveRunner(self.scheduler)
    request = InteractiveProcessRequest(
      argv=("./program.py",),
      run_in_workspace=False,
      input_files=binary.digest,
    )
    result = interactive_runner.run_local_interactive_process(request)
    self.assertEqual(result.process_exit_code, 0)

  def test_no_input_files_in_workspace(self) -> None:
    program_text = b'#!/usr/bin/python\nprint("hello")'
    binary = self.create_mock_binary(program_text)
    with self.assertRaises(ValueError):
      InteractiveProcessRequest(
          argv=("/usr/bin/python",),
          run_in_workspace=True,
          input_files=binary.digest
      )

  def test_failed_run(self) -> None:
    console = MockConsole(use_colors=False)
    program_text = b'#!/usr/bin/python\nraise RuntimeError("foo")'
    res = self.single_target_run(
      console=console,
      program_text=program_text,
      spec='some/addr'
    )
    self.assertEqual(res.exit_code, 1)
    self.assertEquals(console.stdout.getvalue(), "Running target: some/addr:addr\n")
    self.assertEquals(console.stderr.getvalue(), "some/addr:addr failed with code 1!\n")
