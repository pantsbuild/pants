# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import PurePath

from pants.base.build_root import BuildRoot
from pants.core.goals.binary import BinaryConfiguration, CreatedBinary
from pants.engine.console import Console
from pants.engine.fs import DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.engine.target import RegisteredTargetTypes, TargetsWithOrigins
from pants.engine.unions import UnionMembership
from pants.option.custom_types import shell_str
from pants.option.global_options import GlobalOptions
from pants.util.contextutil import temporary_dir


class RunOptions(GoalSubsystem):
    """Runs a runnable target."""

    name = "run"

    # NB: To be runnable, there must be a BinaryConfiguration that works with the target.
    required_union_implementations = (BinaryConfiguration,)

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
    targets_with_origins: TargetsWithOrigins,
    options: RunOptions,
    global_options: GlobalOptions,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
) -> Run:
    targets_to_valid_configs = BinaryConfiguration.group_targets_to_valid_subclass_configs(
        targets_with_origins,
        union_membership=union_membership,
        registered_target_types=registered_target_types,
        goal_name=options.name,
        error_if_no_valid_targets=True,
    )

    bulleted_list_sep = "\n  * "

    if len(targets_to_valid_configs) > 1:
        binary_target_addresses = sorted(tgt.address.spec for tgt in targets_to_valid_configs)
        raise ValueError(
            f"The `run` goal only works on one binary target but was given multiple targets that "
            f"can produce a binary:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(binary_target_addresses)}\n\n"
            f"Please select one of these targets to run."
        )

    target, valid_configs = list(targets_to_valid_configs.items())[0]
    if len(valid_configs) > 1:
        possible_config_types = sorted(
            config_type.__class__.__name__ for config_type in valid_configs
        )
        # TODO: improve this error message. (It's never actually triggered yet because we only have
        #  Python implemented with V2.) A better error message would explain to users how they can
        #  resolve the issue.
        raise ValueError(
            f"Multiple of the registered binary implementations work for {target.address} "
            f"(target type {repr(target.alias)}).\n\n"
            f"It is ambiguous which implementation to use. Possible implementations:"
            f"{bulleted_list_sep}{bulleted_list_sep.join(possible_config_types)}."
        )

    binary = await Get[CreatedBinary](BinaryConfiguration, valid_configs[0])

    workdir = global_options.options.pants_workdir

    with temporary_dir(root_dir=workdir, cleanup=True) as tmpdir:
        path_relative_to_build_root = PurePath(tmpdir).relative_to(build_root.path).as_posix()
        workspace.materialize_directory(
            DirectoryToMaterialize(binary.digest, path_prefix=path_relative_to_build_root)
        )

        console.write_stdout(f"Running target: {target.address}\n")
        full_path = PurePath(tmpdir, binary.binary_name).as_posix()
        run_request = InteractiveProcessRequest(
            argv=(full_path, *options.values.args), run_in_workspace=True,
        )

        try:
            result = runner.run_local_interactive_process(run_request)
            exit_code = result.process_exit_code
            if result.process_exit_code == 0:
                console.write_stdout(f"{target.address} ran successfully.\n")
            else:
                console.write_stderr(
                    f"{target.address} failed with code {result.process_exit_code}!\n"
                )

        except Exception as e:
            console.write_stderr(f"Exception when attempting to run {target.address}: {e!r}\n")
            exit_code = -1

    return Run(exit_code)


def rules():
    return [run]
