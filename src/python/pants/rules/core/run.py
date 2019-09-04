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
from pants.util.collections import assert_single_element


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


class RunError(Exception):
  """???"""


@console_rule(Run, [Console, BuildFileAddresses])
def run(console, addresses):
  try:
    address = assert_single_element(list(addresses))
  except (StopIteration, ValueError):
    raise RunError(f"the `run` goal requires exactly one top-level target! received: {addresses}")
  result = yield Get(RunResult, Address, address.to_address())

  if result.status != 0:
    console.write_stderr(f"failed with code {result.status}!\n")
    console.write_stderr(f"stdout: {result.stdout}\n")
    console.write_stderr(f"stderr: {result.stderr}\n")
  else:
    console.write_stdout(result.stdout)
    console.write_stderr(result.stderr)

  yield Run(result.status)


@rule(RunResult, [HydratedTarget])
def coordinator_of_runs(target):
  run_result = yield Get(RunResult, RunTarget, target.adaptor)
  yield run_result


def rules():
  return [
    run,
    coordinator_of_runs,
  ]
