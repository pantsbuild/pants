# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.python.rules.python_test_runner import PyTestResult
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import console_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.core_test_model import Status, TestResult


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
  # This should do an instance match, or canonicalise the adaptor type, or something
  #if isinstance(target.adaptor, PythonTestsAdaptor):
  # See https://github.com/pantsbuild/pants/issues/4535
  if target.adaptor.type_alias == 'python_tests':
    result = yield Get(PyTestResult, HydratedTarget, target)
    yield TestResult(status=result.status, stdout=result.stdout, stderr=result.stderr)
  else:
    raise Exception("Didn't know how to run tests for type {}".format(target.adaptor.type_alias))


def rules():
  return [
      coordinator_of_tests,
      fast_test,
    ]
