# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import console_rule, rule, union
from pants.engine.selectors import Get


# TODO(#6004): use proper Logging singleton, rather than static logger.
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunResult:
  status: int
  stdout: str
  stderr: str


class Run(Goal):
  """Runs a runnable target."""

  name = 'run'


@union
class RunTarget:
  pass


@console_rule(Run, [Console, BuildFileAddresses])
def run(console, addresses):
  run_results = yield [Get(RunResult, Address, address.to_address()) for address in addresses]

  exit_codes = []
  for result in run_results:
    exit_codes.append(result.status)
    if result.status != 0:
      console.write_stderr(f"failed with code {result.status}!\n")
      console.write_stderr(f"stdout: {result.stdout}\n")
      console.write_stderr(f"stderr: {result.stderr}\n")
    else:
      console.write_stderr("passed!")
      console.write_stdout(result.stdout)
      console.write_stderr(result.stderr)

  yield Run(max(exit_codes))


@rule(RunResult, [HydratedTarget])
def coordinator_of_runs(target):
  run_result = yield Get(RunResult, RunTarget, target.adaptor)
  yield run_result


def rules():
  return [
    run,
    coordinator_of_runs,
  ]
