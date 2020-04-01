# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath

from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.fs import DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.option.custom_types import shell_str
from pants.option.global_options import GlobalOptions
from pants.rules.core.binary import BinaryImplementation, CreatedBinary
from pants.util.contextutil import temporary_dir


class RunOptions(GoalSubsystem):
    """Runs a runnable target."""

    name = "run"

    # NB: To be runnable, there must be a BinaryImplementation that works with the target.
    required_union_implementations = (BinaryImplementation,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            fingerprint=True,
            help="Arguments to pass directly to the executed target, e.g. "
            '`--run-args="val1 val2 --debug"`',
        )


class Run(Goal):
    subsystem_cls = RunOptions


@goal_rule
async def run(
    console: Console,
    workspace: Workspace,
    runner: InteractiveRunner,
    build_root: BuildRoot,
    addresses: Addresses,
    options: RunOptions,
    global_options: GlobalOptions,
) -> Run:
    address = addresses.expect_single()
    binary = await Get[CreatedBinary](Address, address)

    workdir = global_options.options.pants_workdir

    with temporary_dir(root_dir=workdir, cleanup=True) as tmpdir:
        path_relative_to_build_root = PurePath(tmpdir).relative_to(build_root.path).as_posix()
        workspace.materialize_directory(
            DirectoryToMaterialize(binary.digest, path_prefix=path_relative_to_build_root)
        )

        console.write_stdout(f"Running target: {address}\n")
        full_path = PurePath(tmpdir, binary.binary_name).as_posix()
        run_request = InteractiveProcessRequest(
            argv=(full_path, *options.values.args), run_in_workspace=True,
        )

        try:
            result = runner.run_local_interactive_process(run_request)
            exit_code = result.process_exit_code
            if result.process_exit_code == 0:
                console.write_stdout(f"{address} ran successfully.\n")
            else:
                console.write_stderr(f"{address} failed with code {result.process_exit_code}!\n")

        except Exception as e:
            console.write_stderr(f"Exception when attempting to run {address}: {e!r}\n")
            exit_code = -1

    return Run(exit_code)


def rules():
    return [run]
