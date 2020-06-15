# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath

from pants.base.build_root import BuildRoot
from pants.core.goals.binary import BinaryFieldSet, CreatedBinary
from pants.engine.console import Console
from pants.engine.fs import DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_process import InteractiveProcess, InteractiveRunner
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.engine.target import TargetsToValidFieldSets, TargetsToValidFieldSetsRequest
from pants.option.custom_types import shell_str
from pants.option.global_options import GlobalOptions
from pants.util.contextutil import temporary_dir


class RunOptions(GoalSubsystem):
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
            fingerprint=True,
            passthrough=True,
            help="Arguments to pass directly to the executed target, e.g. "
            '`--run-args="val1 val2 --debug"`',
        )


class Run(Goal):
    subsystem_cls = RunOptions


@goal_rule
async def run(
    options: RunOptions,
    global_options: GlobalOptions,
    console: Console,
    interactive_runner: InteractiveRunner,
    workspace: Workspace,
    build_root: BuildRoot,
) -> Run:
    targets_to_valid_field_sets = await Get[TargetsToValidFieldSets](
        TargetsToValidFieldSetsRequest(
            BinaryFieldSet,
            goal_description=f"the `{options.name}` goal",
            error_if_no_valid_targets=True,
            expect_single_field_set=True,
        )
    )
    field_set = targets_to_valid_field_sets.field_sets[0]
    binary = await Get[CreatedBinary](BinaryFieldSet, field_set)

    workdir = global_options.options.pants_workdir
    with temporary_dir(root_dir=workdir, cleanup=True) as tmpdir:
        path_relative_to_build_root = PurePath(tmpdir).relative_to(build_root.path).as_posix()
        workspace.materialize_directory(
            DirectoryToMaterialize(binary.digest, path_prefix=path_relative_to_build_root)
        )

        full_path = PurePath(tmpdir, binary.binary_name).as_posix()
        process = InteractiveProcess(argv=(full_path, *options.values.args), run_in_workspace=True)
        try:
            result = interactive_runner.run_process(process)
            exit_code = result.exit_code
        except Exception as e:
            console.print_stderr(f"Exception when attempting to run {field_set.address}: {e!r}")
            exit_code = -1

    return Run(exit_code)


def rules():
    return [run]
