# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Mapping, Optional, Tuple

from pants.base.build_root import BuildRoot
from pants.engine.console import Console
from pants.engine.environment import CompleteEnvironment
from pants.engine.fs import Digest, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import InteractiveProcess, InteractiveRunner
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.target import (
    FieldSet,
    NoApplicableTargetsBehavior,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import union
from pants.option.custom_types import shell_str
from pants.option.global_options import GlobalOptions
from pants.util.contextutil import temporary_dir
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init


@union
class RunFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary from a target to run a program/script."""


@frozen_after_init
@dataclass(unsafe_hash=True)
class RunRequest:
    digest: Digest
    # Values in args and in env can contain the format specifier "{chroot}", which will
    # be substituted with the (absolute) chroot path.
    args: Tuple[str, ...]
    extra_env: FrozenDict[str, str]

    def __init__(
        self,
        *,
        digest: Digest,
        args: Iterable[str],
        extra_env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.digest = digest
        self.args = tuple(args)
        self.extra_env = FrozenDict(extra_env or {})


class RunSubsystem(GoalSubsystem):
    name = "run"
    help = (
        "Runs a binary target.\n\nThis goal propagates the return code of the underlying "
        "executable. Run `echo $?` to inspect the resulting return code."
    )

    required_union_implementations = (RunFieldSet,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help="Arguments to pass directly to the executed target, e.g. "
            '`--run-args="val1 val2 --debug"`',
        )

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)


class Run(Goal):
    subsystem_cls = RunSubsystem


@goal_rule
async def run(
    run_subsystem: RunSubsystem,
    global_options: GlobalOptions,
    console: Console,
    interactive_runner: InteractiveRunner,
    workspace: Workspace,
    build_root: BuildRoot,
    complete_env: CompleteEnvironment,
) -> Run:
    targets_to_valid_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            RunFieldSet,
            goal_description="the `run` goal",
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.error,
            expect_single_field_set=True,
        ),
    )
    field_set = targets_to_valid_field_sets.field_sets[0]
    request = await Get(RunRequest, RunFieldSet, field_set)

    with temporary_dir(root_dir=global_options.options.pants_workdir, cleanup=True) as tmpdir:
        workspace.write_digest(
            request.digest, path_prefix=PurePath(tmpdir).relative_to(build_root.path).as_posix()
        )

        args = (arg.format(chroot=tmpdir) for arg in request.args)
        env = {**complete_env, **{k: v.format(chroot=tmpdir) for k, v in request.extra_env.items()}}
        try:
            result = interactive_runner.run(
                InteractiveProcess(
                    argv=(*args, *run_subsystem.args),
                    env=env,
                    run_in_workspace=True,
                )
            )
            exit_code = result.exit_code
        except Exception as e:
            console.print_stderr(f"Exception when attempting to run {field_set.address}: {e!r}")
            exit_code = -1

    return Run(exit_code)


def rules():
    return collect_rules()
