# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from textwrap import dedent

from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.rules.core.test import Status, TestResult, coordinator_of_tests, fast_test
from pants_test.engine.util import MockConsole, run_rule
from pants_test.test_base import TestBase


class TestTest(TestBase):
  def single_target_test(self, result, expected_console_output, success=True):
    console = MockConsole(use_colors=False)

    res = run_rule(fast_test, console, (self.make_build_target_address("some/target"),), {
      (TestResult, Address): lambda _: result,
    })

    self.assertEquals(console.stdout.getvalue(), expected_console_output)
    self.assertEquals(0 if success else 1, res.exit_code)

  def make_build_target_address(self, spec):
    address = Address.parse(spec)
    return BuildFileAddress(
      build_file=None,
      target_name=address.target_name,
      rel_path='{}/BUILD'.format(address.spec_path),
    )

  def test_outputs_success(self):
    self.single_target_test(
      result=TestResult(status=Status.SUCCESS, stdout='Here is some output from a test', stderr=''),
      expected_console_output=dedent("""\
        some/target stdout:
        Here is some output from a test

        some/target                                                                     .....   SUCCESS
      """),
    )

  def test_output_failure(self):
    self.single_target_test(
      result=TestResult(status=Status.FAILURE, stdout='Here is some output from a test', stderr=''),
      expected_console_output=dedent("""\
        some/target stdout:
        Here is some output from a test

        some/target                                                                     .....   FAILURE
        """),
      success=False,
    )

  def test_output_mixed(self):
    console = MockConsole(use_colors=False)
    target1 = self.make_build_target_address("testprojects/tests/python/pants/passes")
    target2 = self.make_build_target_address("testprojects/tests/python/pants/fails")

    def make_result(target):
      if target == target1:
        return TestResult(status=Status.SUCCESS, stdout='I passed\n', stderr='')
      elif target == target2:
        return TestResult(status=Status.FAILURE, stdout='I failed\n', stderr='')
      else:
        raise Exception("Unrecognised target")

    res = run_rule(fast_test, console, (target1, target2), {
      (TestResult, Address): make_result,
    })

    self.assertEqual(1, res.exit_code)
    self.assertEquals(console.stdout.getvalue(), dedent("""\
      testprojects/tests/python/pants/passes stdout:
      I passed

      testprojects/tests/python/pants/fails stdout:
      I failed


      testprojects/tests/python/pants/passes                                          .....   SUCCESS
      testprojects/tests/python/pants/fails                                           .....   FAILURE
      """))

  def test_stderr(self):
    self.single_target_test(
      result=TestResult(status=Status.FAILURE, stdout='', stderr='Failure running the tests!'),
      expected_console_output=dedent("""\
        some/target stderr:
        Failure running the tests!

        some/target                                                                     .....   FAILURE
        """),
      success=False,
    )

  def test_coordinator_python_test(self):
    target_adaptor = PythonTestsAdaptor(type_alias='python_tests')
    with self.captured_logging(logging.INFO):
      result = run_rule(coordinator_of_tests, HydratedTarget(Address.parse("some/target"), target_adaptor, ()), {
        (TestResult, PythonTestsAdaptor): lambda _: TestResult(status=Status.FAILURE, stdout='foo', stderr=''),
      })

    self.assertEqual(result, TestResult(status=Status.FAILURE, stdout='foo', stderr=''))
