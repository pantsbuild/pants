# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.console import Console
from pants.engine.fs import DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.rules import console_rule
from pants.engine.selectors import Get
from pants.rules.core.binary import CreatedBinary
from pants.util.contextutil import temporary_dir


class RunOptions(GoalSubsystem):
  """Runs a runnable target."""
  name = 'run'


class Run(Goal):
  subsystem_cls = RunOptions


@console_rule
async def run(
  console: Console,
  workspace: Workspace,
  runner: InteractiveRunner,
  build_root: BuildRoot,
  bfa: BuildFileAddress,
) -> Run:
  target = bfa.to_address()
  binary = await Get[CreatedBinary](Address, target)

  with temporary_dir(root_dir=str(Path(build_root.path, ".pants.d")), cleanup=True) as tmpdir:
    path_relative_to_build_root = str(Path(tmpdir).relative_to(build_root.path))
    workspace.materialize_directory(
      DirectoryToMaterialize(binary.digest, path_prefix=path_relative_to_build_root)
    )

    console.write_stdout(f"Running target: {target}\n")
    full_path = str(Path(tmpdir, binary.binary_name))
    run_request = InteractiveProcessRequest(
      argv=(full_path,),
      run_in_workspace=True,
    )

    try:
      result = runner.run_local_interactive_process(run_request)
      exit_code = result.process_exit_code
      if result.process_exit_code == 0:
        console.write_stdout(f"{target} ran successfully.\n")
      else:
        console.write_stderr(f"{target} failed with code {result.process_exit_code}!\n")

    except Exception as e:
      console.write_stderr(f"Exception when attempting to run {target} : {e}\n")
      exit_code = -1

  return Run(exit_code)


def rules():
  return [run]
