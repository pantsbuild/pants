# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import Path

from pants.engine.console import Console
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DirectoryToMaterialize,
    FileContent,
    MaterializeDirectoriesResult,
    MaterializeDirectoryResult,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import RootRule, goal_rule
from pants.engine.selectors import Get
from pants.fs.fs import is_child_of
from pants.testutil.goal_rule_test_base import GoalRuleTestBase
from pants.testutil.test_base import TestBase


@dataclass(frozen=True)
class MessageToGoalRule:
    create_digest: CreateDigest


class MockWorkspaceGoalOptions(GoalSubsystem):
    name = "mock-workspace-goal"


class MockWorkspaceGoal(Goal):
    subsystem_cls = MockWorkspaceGoalOptions


@goal_rule
async def workspace_goal_rule(
    console: Console, workspace: Workspace, msg: MessageToGoalRule
) -> MockWorkspaceGoal:
    digest = await Get(Digest, CreateDigest, msg.create_digest)
    output = workspace.materialize_directory(DirectoryToMaterialize(digest))
    console.print_stdout(output.output_paths[0], end="")
    return MockWorkspaceGoal(exit_code=0)


class WorkspaceInGoalRuleTest(GoalRuleTestBase):
    """This test is meant to ensure that the Workspace type successfully invokes the rust FFI
    function to write to disk in the context of a @goal_rule, without crashing or otherwise
    failing."""

    goal_cls = MockWorkspaceGoal

    @classmethod
    def rules(cls):
        return super().rules() + [RootRule(MessageToGoalRule), workspace_goal_rule]

    def test(self):
        msg = MessageToGoalRule(
            create_digest=CreateDigest([FileContent(path="a.txt", content=b"hello")])
        )
        output_path = Path(self.build_root, "a.txt")
        self.assert_console_output_contains(str(output_path), additional_params=[msg])
        assert output_path.read_text() == "hello"


# TODO(gshuflin) - it would be nice if this test, which tests that the MaterializeDirectoryResults value
# is valid, could be subsumed into the above @goal_rule-based test, but it's a bit awkward
# to get the MaterializeDirectoriesResult out of a @goal_rule at the moment.
class FileSystemTest(TestBase):
    def test_workspace_materialize_directories_result(self):
        # TODO(#8336): at some point, this test should require that Workspace only be invoked from an @goal_rule
        workspace = Workspace(self.scheduler)

        digest = self.request_single_product(
            Digest,
            CreateDigest(
                [
                    FileContent(path="a.txt", content=b"hello"),
                    FileContent(path="subdir/b.txt", content=b"goodbye"),
                ]
            ),
        )

        path1 = Path("a.txt")
        path2 = Path("subdir/b.txt")

        assert not path1.is_file()
        assert not path2.is_file()

        output = workspace.materialize_directories((DirectoryToMaterialize(digest),))

        assert type(output) == MaterializeDirectoriesResult
        materialize_result = output[0]
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
