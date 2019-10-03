# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
from pants.engine.rules import console_rule
from pants.engine.selectors import Get
from pants.util.contextutil import temporary_dir
from pants_test.console_rule_test_base import ConsoleRuleTestBase
from pants_test.test_base import TestBase


class TestWorkspaceGoal(Goal):
  name = 'test-workspace-goal'


@console_rule
def workspace_console_rule(console: Console, workspace: Workspace) -> TestWorkspaceGoal:
  input_files_content = InputFilesContent((
    FileContent(path='a.txt', content=b'hello', is_executable=False),
  ))
  digest = yield Get(Digest, InputFilesContent, input_files_content)
  with temporary_dir() as tmp_dir:
    output = workspace.materialize_directories((
      DirectoryToMaterialize(path=tmp_dir, directory_digest=digest),
    ))
  result = output.dependencies[0]
  console.print_stdout(f"Wrote file: {result.output_paths[0]}")
  yield TestWorkspaceGoal(exit_code=0)


class WorkspaceInConsoleRuleTest(ConsoleRuleTestBase):
  """This test is meant to ensure that the Workspace type successfully
  invokes the rust FFI function to write to disk in the context of a @console_rule,
  without crashing or otherwise failing."""
  goal_cls = TestWorkspaceGoal

  @classmethod
  def rules(cls):
    return super().rules() + [workspace_console_rule]

  def test_basic(self):
    self.assert_console_output_contains("Wrote file: a.txt")


class FileSystemTest(TestBase):
  def test_materialize(self):
    #TODO(#8336): at some point, this test should require that Workspace only be invoked from a console_role
    workspace = Workspace(self.scheduler)

    input_files_content = InputFilesContent((
      FileContent(path='a.txt', content=b'hello', is_executable=False),
      FileContent(path='subdir/b.txt', content=b'goodbye', is_executable=False),
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
      self.assertEqual(materialize_result.output_paths, ('a.txt', 'subdir/b.txt',))
