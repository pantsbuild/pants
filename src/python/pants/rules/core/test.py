# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import console_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.core_test_model import Status, TestResult, TestTarget


# TODO(#6004): use proper Logging singleton, rather than static logger.
logger = logging.getLogger(__name__)


class Test(Goal):
  """Runs tests."""

  name = 'test'


@console_rule(Test, [Console, BuildFileAddresses])
def fast_test(console, addresses):
  test_results = yield [Get(TestResult, Address, address.to_address()) for address in addresses]
  did_any_fail = False
  for address, test_result in zip(addresses, test_results):
    if test_result.status == Status.FAILURE:
      did_any_fail = True
    if test_result.stdout:
      console.write_stdout(
        "{} stdout:\n{}\n".format(
          address.reference(),
          console.red(test_result.stdout) if test_result.status == Status.FAILURE else test_result.stdout
        )
      )
    if test_result.stderr:
      # NB: we write to stdout, rather than to stderr, to avoid potential issues interleaving the
      # two streams.
      console.write_stdout(
        "{} stderr:\n{}\n".format(
          address.reference(),
          console.red(test_result.stderr) if test_result.status == Status.FAILURE else test_result.stderr
        )
      )

  console.write_stdout("\n")

  for address, test_result in zip(addresses, test_results):
    console.print_stdout('{0:80}.....{1:>10}'.format(address.reference(), test_result.status.value))

  if did_any_fail:
    console.print_stderr(console.red('Tests failed'))
    exit_code = PANTS_FAILED_EXIT_CODE
  else:
    exit_code = PANTS_SUCCEEDED_EXIT_CODE

  yield Test(exit_code)


@rule(TestResult, [HydratedTarget])
def coordinator_of_tests(target):
  # TODO(#6004): when streaming to live TTY, rely on V2 UI for this information. When not a
  # live TTY, periodically dump heavy hitters to stderr. See
  # https://github.com/pantsbuild/pants/issues/6004#issuecomment-492699898.
  logger.info("Starting tests: {}".format(target.address.reference()))
  # NB: This has the effect of "casting" a TargetAdaptor to a member of the TestTarget union. If the
  # TargetAdaptor is not a member of the union, it will fail at runtime with a useful error message.
  result = yield Get(TestResult, TestTarget, target.adaptor)
  logger.info("Tests {}: {}".format(
    "succeeded" if result.status == Status.SUCCESS else "failed",
    target.address.reference(),
  ))
  yield result


def rules():
  return [
      coordinator_of_tests,
      fast_test,
    ]
