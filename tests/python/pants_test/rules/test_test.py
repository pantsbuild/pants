# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from textwrap import dedent

from pants.base.specs import DescendantAddresses, SingleAddress
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.build_files import AddressProvenanceMap
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.legacy.structs import PythonBinaryAdaptor, PythonTestsAdaptor
from pants.engine.rules import UnionMembership
from pants.rules.core.core_test_model import TestTarget
from pants.rules.core.test import (
  AddressAndTestResult,
  Status,
  TestResult,
  coordinator_of_tests,
  fast_test,
)
from pants.testutil.engine.util import MockConsole, MockedYieldGet, run_rule
from pants.testutil.test_base import TestBase


class TestTest(TestBase):
  def single_target_test(self, result, expected_console_output, success=True):
    console = MockConsole(use_colors=False)

    addr = self.make_build_target_address("some/target")
    res = run_rule(
      fast_test,
      rule_args=[console, (addr,)],
      mocked_yield_gets=[
        MockedYieldGet(
          product_type=AddressAndTestResult,
          subject_type=Address,
          mock=lambda _: AddressAndTestResult(addr, result),
        ),
      ],
    )

    self.assertEquals(console.stdout.getvalue(), expected_console_output)
    self.assertEquals(0 if success else 1, res.exit_code)

  @staticmethod
  def make_build_target_address(spec):
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
        tr = TestResult(status=Status.SUCCESS, stdout='I passed\n', stderr='')
      elif target == target2:
        tr = TestResult(status=Status.FAILURE, stdout='I failed\n', stderr='')
      else:
        raise Exception("Unrecognised target")
      return AddressAndTestResult(target, tr)

    res = run_rule(
      fast_test,
      rule_args=[console, (target1, target2)],
      mocked_yield_gets=[
        MockedYieldGet(product_type=AddressAndTestResult, subject_type=Address, mock=make_result),
      ],
    )

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
    addr = Address.parse("some/target")
    target_adaptor = PythonTestsAdaptor(type_alias='python_tests')
    with self.captured_logging(logging.INFO):
      result = run_rule(
        coordinator_of_tests,
        rule_args=[
          HydratedTarget(addr, target_adaptor, ()),
          UnionMembership(union_rules={TestTarget: [PythonTestsAdaptor]}),
          AddressProvenanceMap(bfaddr_to_spec={}),
        ],
        mocked_yield_gets=[
          MockedYieldGet(
            product_type=TestResult,
            subject_type=PythonTestsAdaptor,
            mock=lambda _: TestResult(status=Status.FAILURE, stdout='foo', stderr=''),
          ),
        ],
      )

    self.assertEqual(
      result,
      AddressAndTestResult(addr, TestResult(status=Status.FAILURE, stdout='foo', stderr=''))
    )

  def test_globbed_test_target(self):
    bfaddr = BuildFileAddress(None, 'tests', 'some/dir')
    target_adaptor = PythonTestsAdaptor(type_alias='python_tests')
    with self.captured_logging(logging.INFO):
      result = run_rule(
        coordinator_of_tests,
        rule_args=[
          HydratedTarget(bfaddr.to_address(), target_adaptor, ()),
          UnionMembership(union_rules={TestTarget: [PythonTestsAdaptor]}),
          AddressProvenanceMap(bfaddr_to_spec={bfaddr: DescendantAddresses(directory='some/dir')}),
        ],
        mocked_yield_gets=[
          MockedYieldGet(
            product_type=TestResult,
            subject_type=PythonTestsAdaptor,
            mock=lambda _: TestResult(status=Status.SUCCESS, stdout='foo', stderr=''),
          ),
        ],
      )

      self.assertEqual(
        result,
        AddressAndTestResult(bfaddr.to_address(),
                             TestResult(status=Status.SUCCESS, stdout='foo', stderr=''))
      )

  def test_globbed_non_test_target(self):
    bfaddr = BuildFileAddress(None, 'bin', 'some/dir')
    target_adaptor = PythonBinaryAdaptor(type_alias='python_binary')
    with self.captured_logging(logging.INFO):
      result = run_rule(
        coordinator_of_tests,
        rule_args=[
          HydratedTarget(bfaddr.to_address(), target_adaptor, ()),
          UnionMembership(union_rules={TestTarget: [PythonTestsAdaptor]}),
          AddressProvenanceMap(bfaddr_to_spec={bfaddr: DescendantAddresses(directory='some/dir')}),
        ],
        mocked_yield_gets=[
          MockedYieldGet(
            product_type=TestResult,
            subject_type=PythonTestsAdaptor,
            mock=lambda _: TestResult(status=Status.SUCCESS, stdout='foo', stderr=''),
          ),
        ],
      )

      self.assertEqual(
        result,
        AddressAndTestResult(bfaddr.to_address(), None)
      )

  def test_single_non_test_target(self):
    bfaddr = BuildFileAddress(None, 'bin', 'some/dir')
    target_adaptor = PythonBinaryAdaptor(type_alias='python_binary')
    with self.captured_logging(logging.INFO):
      # Note that this is not the same error message the end user will see, as we're resolving
      # union Get requests in run_rule, not the real engine.  But this test still asserts that
      # we error when we expect to error.
      with self.assertRaisesRegex(AssertionError, r'Rule requested: .* which cannot be satisfied.'):
        run_rule(
          coordinator_of_tests,
          rule_args=[
            HydratedTarget(bfaddr.to_address(), target_adaptor, ()),
            UnionMembership(union_rules={TestTarget: [PythonTestsAdaptor]}),
            AddressProvenanceMap(bfaddr_to_spec={
              bfaddr: SingleAddress(directory='some/dir', name='bin'),
            }),
          ],
          mocked_yield_gets=[
            MockedYieldGet(
              product_type=TestResult,
              subject_type=PythonTestsAdaptor,
              mock=lambda _: TestResult(status=Status.SUCCESS, stdout='foo', stderr=''),
            ),
          ],
        )
