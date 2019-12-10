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
from pants.fs.fs import is_child_of
from pants.testutil.console_rule_test_base import ConsoleRuleTestBase
from pants.testutil.test_base import TestBase


@dataclass(frozen=True)
class MessageToConsoleRule:
  input_files_content: InputFilesContent


class MockWorkspaceGoal(Goal):
  name = 'mock-workspace-goal'


@console_rule
async def workspace_console_rule(console: Console, workspace: Workspace, msg: MessageToConsoleRule) -> MockWorkspaceGoal:
  digest = await Get(Digest, InputFilesContent, msg.input_files_content)
  output = workspace.materialize_directory(DirectoryToMaterialize(digest))
  console.print_stdout(output.output_paths[0], end='')
  return MockWorkspaceGoal(exit_code=0)


class WorkspaceInConsoleRuleTest(ConsoleRuleTestBase):
  """This test is meant to ensure that the Workspace type successfully
  invokes the rust FFI function to write to disk in the context of a @console_rule,
  without crashing or otherwise failing."""
  goal_cls = MockWorkspaceGoal

  @classmethod
  def rules(cls):
    return super().rules() + [RootRule(MessageToConsoleRule), workspace_console_rule]

  def test(self):
    msg = MessageToConsoleRule(
      input_files_content=InputFilesContent([FileContent(path='a.txt', content=b'hello')])
    )
    output_path = Path(self.build_root, 'a.txt')
    self.assert_console_output_contains(str(output_path), additional_params=[msg])
    assert output_path.read_text() == "hello"


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

    digest = self.request_single_product(Digest, input_files_content)

    path1 = Path('a.txt')
    path2 = Path('subdir/b.txt')

    assert not path1.is_file()
    assert not path2.is_file()

    output = workspace.materialize_directories((DirectoryToMaterialize(digest),))

    assert type(output) == MaterializeDirectoriesResult
    materialize_result = output.dependencies[0]
    assert type(materialize_result) == MaterializeDirectoryResult
    assert materialize_result.output_paths == tuple(
      str(Path(self.build_root, p)) for p in [path1, path2]
    )


class IsChildOfTest(TestBase):
  def test_is_child_of(self):
    mock_build_root = Path("/mock/build/root")

    assert is_child_of(Path("/mock/build/root/dist/dir"), mock_build_root)
    assert is_child_of(Path("dist/dir"), mock_build_root)
    assert is_child_of(Path("./dist/dir"), mock_build_root)
    assert is_child_of(Path("../root/dist/dir"), mock_build_root)
    assert is_child_of(Path(""), mock_build_root)
    assert is_child_of(Path("./"), mock_build_root)

    assert not is_child_of(Path("/other/random/directory/root/dist/dir"), mock_build_root)
    assert not is_child_of(Path("../not_root/dist/dir"), mock_build_root)

