# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath

from pants.base.build_root import BuildRoot
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.selectors import Get
from pants.option.global_options import GlobalOptions
from pants.util.contextutil import temporary_dir


@union
class ReplImplementation:
    """This type proxies from the top-level `repl` goal to a specific REPL implementation for a
    specific language or languages."""

    addresses: Addresses


class ReplOptions(GoalSubsystem):
    """Opens a REPL."""

    name = "repl"
    required_union_implementations = (ReplImplementation,)


class Repl(Goal):
    subsystem_cls = ReplOptions


@dataclass(frozen=True)
class ReplBinary:
    digest: Digest
    binary_name: str


@goal_rule
async def run_repl(
    console: Console,
    workspace: Workspace,
    runner: InteractiveRunner,
    addresses: Addresses,
    build_root: BuildRoot,
    union_membership: UnionMembership,
    global_options: GlobalOptions,
) -> Repl:

    # We can guarantee that we will only even enter this `goal_rule` if there exists an implementer
    # of the `ReplImplementation` union because `LegacyGraphSession.run_goal_rules()` will not
    # execute this rule's body if there are no implementations registered.
    repl_impl = next(iter(union_membership.union_rules[ReplImplementation]))
    repl_binary = await Get[ReplBinary](ReplImplementation, repl_impl(addresses))

    with temporary_dir(root_dir=global_options.pants_workdir, cleanup=False) as tmpdir:
        path_relative_to_build_root = PurePath(tmpdir).relative_to(build_root.path).as_posix()
        workspace.materialize_directory(
            DirectoryToMaterialize(repl_binary.digest, path_prefix=path_relative_to_build_root)
        )

        full_path = PurePath(tmpdir, repl_binary.binary_name).as_posix()
        run_request = InteractiveProcessRequest(argv=(full_path,), run_in_workspace=True,)

    result = runner.run_local_interactive_process(run_request)
    exit_code = result.process_exit_code

    if exit_code == 0:
        console.write_stdout("REPL exited successfully.")
    else:
        console.write_stdout(f"REPL exited with error: {exit_code}.")

    return Repl(exit_code)


def rules():
    return [
        run_repl,
    ]
