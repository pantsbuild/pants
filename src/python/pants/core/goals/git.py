# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import PurePath

from pants.base.build_root import BuildRoot
from pants.core.util_rules.subprocess_environment import SubprocessEnvironmentVars
from pants.engine.console import Console
from pants.engine.environment import Environment, EnvironmentRequest
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get
from pants.engine.process import (
    BinaryNotFoundError,
    BinaryPathRequest,
    BinaryPaths,
    FallibleProcessResult,
    Process,
    ProcessCacheScope,
    SearchPath,
)
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.option.custom_types import dir_option, shell_str
from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class Git:
    exe: str


@rule
async def find_git() -> Git:
    environment = await Get(Environment, EnvironmentRequest(requested=["PATH"]))
    path = environment["PATH"].split(os.pathsep)
    git_request = BinaryPathRequest(search_path=SearchPath(path), binary_name="git")
    git_paths = await Get(BinaryPaths, BinaryPathRequest, git_request)
    git_path = git_paths.first_path
    if git_path is None:
        raise BinaryNotFoundError(git_request)
    return Git(git_path.path)


@dataclass(frozen=True)
class GitCommand:
    argv: tuple[str, ...]
    env: FrozenDict[str, str]
    git_work_tree: PurePath | None = None
    git_dir: PurePath | None = None


@dataclass(frozen=True)
class GitResult:
    result: FallibleProcessResult


@rule
async def execute_git(git: Git, git_command: GitCommand, build_root: BuildRoot) -> GitResult:
    git_work_tree = git_command.git_work_tree or build_root.pathlib_path
    git_dir = git_command.git_dir or git_work_tree / ".git"
    return GitResult(
        await Get(
            FallibleProcessResult,
            Process(
                description=f"Run GIT_DIR={git_dir} GIT_WORK_TREE={git_work_tree} git ...",
                argv=[git.exe, *git_command.argv],
                env={
                    **git_command.env,
                    "GIT_DIR": str(git_dir),
                    "GIT_WORK_TREE": str(git_work_tree),
                },
                cache_scope=ProcessCacheScope.NEVER,
            ),
        )
    )


class GitSubsystem(GoalSubsystem):
    name = "git"
    help = "Run git."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help="Arguments to pass to git.",
        )
        register("--work-tree", type=dir_option, help="The path to the git worktree.")
        register("--dir", type=dir_option, help="The path to the .git dir.")

    @property
    def work_tree(self) -> PurePath | None:
        return PurePath(self.options.work_tree) if self.options.work_tree else None

    @property
    def dir(self) -> PurePath | None:
        return PurePath(self.options.dir) if self.options.dir else None


class GitGoal(Goal):
    subsystem_cls = GitSubsystem


@goal_rule
async def run_git(
    git: GitSubsystem, subprocess_env_vars: SubprocessEnvironmentVars, console: Console
) -> GitGoal:
    git_result = await Get(
        GitResult,
        GitCommand(
            argv=tuple(git.options.args),
            env=subprocess_env_vars.vars,
            git_work_tree=git.work_tree,
            git_dir=git.dir,
        ),
    )
    result = git_result.result
    if result.stdout:
        console.write_stdout(result.stdout.decode())
    if result.stderr:
        console.write_stderr(result.stderr.decode())
    return GitGoal(result.exit_code)


def rules():
    return collect_rules()
