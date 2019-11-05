# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.rules import console_rule


class Run(Goal):
  """Runs a runnable target."""
  name = 'v2-run'


@console_rule
def run(console: Console, runner: InteractiveRunner, build_file_addresses: BuildFileAddresses) -> Run:
  console.write_stdout("Running the `run` goal\n")

  request = InteractiveProcessRequest(
    argv=["/usr/bin/python"],
    env=("TEST_ENV", "TEST"),
    run_in_workspace=False,
  )

  try:
    res = runner.run_local_interactive_process(request)
    print(f"Subprocess exited with result: {res.process_exit_code}")
    yield Run(res.process_exit_code)
  except Exception as e:
    print(f"Exception when running local interactive process: {e}")
    yield Run(-1)


def rules():
  return [run]
