# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.fs import Digest, FileContent, InputFilesContent, Workspace
from pants.engine.interactive_runner import InteractiveRunner
from pants.rules.core import run
from pants.rules.core.binary import CreatedBinary
from pants.testutil.console_rule_test_base import ConsoleRuleTestBase
from pants.testutil.engine.util import MockConsole, run_rule


class RunTest(ConsoleRuleTestBase):
  goal_cls = run.Run

  def create_mock_binary(self, program_text: bytes) -> CreatedBinary:
    input_files_content = InputFilesContent((
      FileContent(path='program.py', content=program_text, is_executable=True),
    ))
    digest, = self.scheduler.product_request(Digest, [input_files_content])
    return CreatedBinary(
      binary_name='program.py',
      digest=digest,
    )

  def single_target_run(self, *, console: MockConsole, program_text: bytes, spec: str):
    workspace = Workspace(self.scheduler)
    interactive_runner = InteractiveRunner(self.scheduler)
    address = Address.parse(spec)
    bfa =  BuildFileAddress(
      build_file=None,
      target_name=address.target_name,
      rel_path=f'{address.spec_path}/BUILD'
    )
    res = run_rule(run.run, console, workspace, interactive_runner, bfa, {
      (CreatedBinary, Address): lambda _: self.create_mock_binary(program_text)
    })
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
