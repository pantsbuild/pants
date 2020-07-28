# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Mapping, Optional, Tuple

from pants.base.build_root import BuildRoot
from pants.core.goals.binary import BinaryFieldSet
from pants.engine.console import Console
from pants.engine.fs import Digest, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import InteractiveProcess, InteractiveRunner
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.target import TargetsToValidFieldSets, TargetsToValidFieldSetsRequest
from pants.option.custom_types import shell_str
from pants.option.global_options import GlobalOptions
from pants.util.contextutil import temporary_dir
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init


@frozen_after_init
@dataclass(unsafe_hash=True)
class RunRequest:
    digest: Digest
    binary_name: str
    prefix_args: Tuple[str, ...]
    env: FrozenDict[str, str]

    def __init__(
        self,
        *,
        digest: Digest,
        binary_name: str,
        prefix_args: Optional[Iterable[str]] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.digest = digest
        self.binary_name = binary_name
        self.prefix_args = tuple(prefix_args or ())
        self.env = FrozenDict(env or {})


class RunSubsystem(GoalSubsystem):
    """Runs a binary target.

    This goal propagates the return code of the underlying executable. Run `echo $?` to inspect the
    resulting return code.
    """

    name = "run"

    # NB: To be runnable, there must be a BinaryFieldSet that works with the target.
    required_union_implementations = (BinaryFieldSet,)

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
) -> Run:
    targets_to_valid_field_sets = await Get(
        TargetsToValidFieldSets,
        TargetsToValidFieldSetsRequest(
            BinaryFieldSet,
            goal_description="the `run` goal",
            error_if_no_valid_targets=True,
            expect_single_field_set=True,
        ),
    )
    field_set = targets_to_valid_field_sets.field_sets[0]
    request = await Get(RunRequest, BinaryFieldSet, field_set)

    with temporary_dir(root_dir=global_options.options.pants_workdir, cleanup=True) as tmpdir:
        tmpdir_relative_path = PurePath(tmpdir).relative_to(build_root.path).as_posix()
        workspace.write_digest(request.digest, path_prefix=tmpdir_relative_path)

        exe_path = PurePath(tmpdir, request.binary_name).as_posix()
        process = InteractiveProcess(
            argv=(exe_path, *request.prefix_args, *run_subsystem.args),
            env=request.env,
            run_in_workspace=True,
        )
        try:
            result = interactive_runner.run(process)
            exit_code = result.exit_code
        except Exception as e:
            console.print_stderr(f"Exception when attempting to run {field_set.address}: {e!r}")
            exit_code = -1

    return Run(exit_code)


def rules():
    return collect_rules()
