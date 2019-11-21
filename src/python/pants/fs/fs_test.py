# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import Path

from pants.engine.console import Console
from pants.engine.fs import (
  Digest,
  DirectoryToMaterialize,
  FileContent,
  InputFilesContent,
  MaterializeDirectoriesResult,
  MaterializeDirectoryResult,
  Workspace,
)
from pants.engine.goal import Goal
from pants.engine.rules import RootRule, console_rule
from pants.engine.selectors import Get
from pants.testutil.console_rule_test_base import ConsoleRuleTestBase
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir


@dataclass(frozen=True)
class MessageToConsoleRule:
  tmp_dir: str
  input_files_content: InputFilesContent


class MockWorkspaceGoal(Goal):
  name = 'mock-workspace-goal'


@console_rule
def workspace_console_rule(console: Console, workspace: Workspace, msg: MessageToConsoleRule) -> MockWorkspaceGoal:
  digest = yield Get(Digest, InputFilesContent, msg.input_files_content)
  output = workspace.materialize_directories((
    DirectoryToMaterialize(path=msg.tmp_dir, directory_digest=digest),
  ))
  output_path = output.dependencies[0].output_paths[0]
  console.print_stdout(str(Path(msg.tmp_dir, output_path)), end='')
  yield MockWorkspaceGoal(exit_code=0)


class WorkspaceInConsoleRuleTest(ConsoleRuleTestBase):
  """This test is meant to ensure that the Workspace type successfully
  invokes the rust FFI function to write to disk in the context of a @console_rule,
  without crashing or otherwise failing."""
  goal_cls = MockWorkspaceGoal

  @classmethod
  def rules(cls):
    return super().rules() + [RootRule(MessageToConsoleRule), workspace_console_rule]

  def test(self):
    with temporary_dir() as tmp_dir:
      input_files_content = InputFilesContent((
        FileContent(path='a.txt', content=b'hello'),
      ))

      msg = MessageToConsoleRule(tmp_dir=tmp_dir, input_files_content=input_files_content)
      output_path = str(Path(tmp_dir, 'a.txt'))
      self.assert_console_output_contains(output_path, additional_params=[msg])
      contents = open(output_path).read()
      self.assertEqual(contents, 'hello')


#TODO(gshuflin) - it would be nice if this test, which tests that the MaterializeDirectoryResults value
# is valid, could be subsumed into the above @console_rule-based test, but it's a bit awkward
# to get the MaterializeDirectoriesResult out of a @console_rule at the moment.
class FileSystemTest(TestBase):
  def test_workspace_materialize_directories_result(self):
    #TODO(#8336): at some point, this test should require that Workspace only be invoked from a console_role
    workspace = Workspace(self.scheduler)

    input_files_content = InputFilesContent((
      FileContent(path='a.txt', content=b'hello'),
      FileContent(path='subdir/b.txt', content=b'goodbye'),
    ))

    digest, = self.scheduler.product_request(Digest, [input_files_content])

    with temporary_dir() as tmp_dir:
      path1 = Path(tmp_dir, 'a.txt')
      path2 = Path(tmp_dir, 'subdir', 'b.txt')

      self.assertFalse(path1.is_file())
      self.assertFalse(path2.is_file())

      output = workspace.materialize_directories((
        DirectoryToMaterialize(path=tmp_dir, directory_digest=digest),
      ))

      self.assertEqual(type(output), MaterializeDirectoriesResult)
      materialize_result = output.dependencies[0]
      self.assertEqual(type(materialize_result), MaterializeDirectoryResult)
      self.assertEqual(materialize_result.output_paths,
        (str(Path(tmp_dir, 'a.txt')), str(Path(tmp_dir, 'subdir/b.txt')),)
      )
