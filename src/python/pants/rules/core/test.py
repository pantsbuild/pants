# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from builtins import str

from pants.backend.python.rules.python_test_runner import PyTestResult
from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import console_rule, rule
from pants.engine.selectors import Get, Select
from pants.rules.core.core_test_model import Status, TestResult
from pants.rules.core.exceptions import GracefulTerminationException


@console_rule('test', [Select(Console), Select(BuildFileAddresses)])
def fast_test(console, addresses):
  test_results = yield [Get(TestResult, Address, address.to_address()) for address in addresses]
  wrote_any_stdout = False
  did_any_fail = False
  for test_result in test_results:
    wrote_any_stdout |= bool(test_result.stdout)
    # Assume \n-terminated
    console.write_stdout(test_result.stdout)
    if test_result.stdout and not test_result.stdout[-1] == '\n':
      console.write_stdout(str('\n'))
    if test_result.status == Status.FAILURE:
      did_any_fail = True

  if wrote_any_stdout:
    console.write_stdout(str('\n'))

  for address, test_result in zip(addresses, test_results):
    console.print_stdout(str('{0:80}.....{1:>10}'.format(address.reference(), test_result.status)))

  if did_any_fail:
    raise GracefulTerminationException("Tests failed", exit_code=1)


@rule(TestResult, [Select(HydratedTarget)])
def coordinator_of_tests(target):
  # This should do an instance match, or canonicalise the adaptor type, or something
  #if isinstance(target.adaptor, PythonTestsAdaptor):
  # See https://github.com/pantsbuild/pants/issues/4535
  if target.adaptor.type_alias == 'python_tests':
    result = yield Get(PyTestResult, HydratedTarget, target)
    yield TestResult(status=result.status, stdout=result.stdout)
  else:
    raise Exception("Didn't know how to run tests for type {}".format(target.adaptor.type_alias))
