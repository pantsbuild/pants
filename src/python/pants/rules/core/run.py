# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path

from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.rules import console_rule
from pants.engine.selectors import Get
from pants.rules.core.binary import CreatedBinary
from pants.util.contextutil import temporary_dir


class Run(Goal):
  """Runs a runnable target."""
  name = 'run'


@console_rule
def run(console: Console, workspace: Workspace, runner: InteractiveRunner, addresses: BuildFileAddresses) -> Run:
  binaries = yield [Get(CreatedBinary, Address, address.to_address()) for address in addresses]

  exit_codes = []
  for (binary, bfa) in zip(binaries, addresses):
    target = bfa.to_address()
    with temporary_dir(cleanup=False) as tmpdir:
      dirs_to_materialize = (DirectoryToMaterialize(path=str(tmpdir), directory_digest=binary.digest),)
      workspace.materialize_directories(dirs_to_materialize)

      console.write_stdout(f"Running target: {target}\n")
      full_path = str(Path(tmpdir, binary.command))
      run_request = InteractiveProcessRequest(
        argv=[full_path],
        run_in_workspace=True,
      )

      try:
        result = runner.run_local_interactive_process(run_request)
        exit_codes.append(result.process_exit_code)
        if result.process_exit_code == 0:
          console.write_stdout(f"{target} ran successfully.\n")
        else:
          console.write_stderr(f"{target} failed with code {result.process_exit_code}!\n")

      except Exception as e:
        console.write_stderr(f"Exception when attempting to run {target} : {e}\n")

  overall_exit_code = 0 if all(code == 0 for code in exit_codes) else -1
  yield Run(overall_exit_code)


def rules():
  return [run]
