# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from textwrap import dedent
from typing import Dict, Optional

from pants.base.specs import DescendantAddresses, SingleAddress, Spec
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.build_files import AddressProvenanceMap
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Snapshot
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
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase


class TestTest(TestBase):
  def single_target_test(self, result, expected_console_output, success=True):
    console = MockConsole(use_colors=False)
    addr = self.make_build_target_address("some/target")
    res = run_rule(
      fast_test,
      rule_args=[console, (addr,)],
      mock_gets=[
        MockGet(
          product_type=AddressAndTestResult,
          subject_type=Address,
          mock=lambda _: AddressAndTestResult(addr, result),
        ),
      ],
    )
    assert console.stdout.getvalue() == expected_console_output
    assert (0 if success else 1) == res.exit_code

  @staticmethod
  def make_build_target_address(spec):
    address = Address.parse(spec)
    return BuildFileAddress(
      build_file=None,
      target_name=address.target_name,
      rel_path=f'{address.spec_path}/BUILD',
    )

  def test_output_success(self):
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
      mock_gets=[
        MockGet(product_type=AddressAndTestResult, subject_type=Address, mock=make_result),
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

  def run_coordinator_of_tests(
    self,
    *,
    address: Address,
    bfaddr_to_spec: Optional[Dict[BuildFileAddress, Spec]] = None,
    test_target_type: bool = True,
    include_sources: bool = True,
  ) -> AddressAndTestResult:
    mocked_fileset = EagerFilesetWithSpec(
      "src",
      {"globs": []},
      snapshot=Snapshot(
        # TODO: this is not robust to set as an empty digest. Add a test util that provides
        #  some premade snapshots and possibly a generalized make_hydrated_target function.
        directory_digest=EMPTY_DIRECTORY_DIGEST,
        files=("test.py",) if include_sources else (),
        dirs=()
      )
    )
    target_adaptor = (
      PythonTestsAdaptor(type_alias='python_tests', sources=mocked_fileset)
      if test_target_type else
      PythonBinaryAdaptor(type_alias='python_binary', sources=mocked_fileset)
    )
    with self.captured_logging(logging.INFO):
      result = run_rule(
        coordinator_of_tests,
        rule_args=[
          HydratedTarget(address, target_adaptor, ()),
          UnionMembership(union_rules={TestTarget: [PythonTestsAdaptor]}),
          AddressProvenanceMap(bfaddr_to_spec=bfaddr_to_spec or {}),
        ],
        mock_gets=[
          MockGet(
            product_type=TestResult,
            subject_type=PythonTestsAdaptor,
            mock=lambda _: TestResult(status=Status.SUCCESS, stdout='foo', stderr=''),
          ),
        ],
      )
    return result

  def test_coordinator_single_test_target(self):
    addr = Address.parse("some/target")
    result = self.run_coordinator_of_tests(address=addr)
    assert result == AddressAndTestResult(
      addr, TestResult(status=Status.SUCCESS, stdout='foo', stderr='')
    )

  def test_coordinator_single_non_test_target(self):
    bfaddr = BuildFileAddress(None, 'bin', 'some/dir')
    # Note that this is not the same error message the end user will see, as we're resolving
    # union Get requests in run_rule, not the real engine.  But this test still asserts that
    # we error when we expect to error.
    with self.assertRaisesRegex(AssertionError, r'Rule requested: .* which cannot be satisfied.'):
      self.run_coordinator_of_tests(
        address=bfaddr.to_address(),
        bfaddr_to_spec={bfaddr: SingleAddress(directory='some/dir', name='bin')},
        test_target_type=False,
      )

  def test_coordinator_empty_sources(self):
    addr = Address.parse("some/target")
    result = self.run_coordinator_of_tests(address=addr, include_sources=False)
    assert result == AddressAndTestResult(addr, None)

  def test_coordinator_globbed_test_target(self):
    bfaddr = BuildFileAddress(None, 'tests', 'some/dir')
    result = self.run_coordinator_of_tests(
      address=bfaddr.to_address(),
      bfaddr_to_spec={bfaddr: DescendantAddresses(directory='some/dir')}
    )
    assert result == AddressAndTestResult(
      bfaddr.to_address(), TestResult(status=Status.SUCCESS, stdout='foo', stderr='')
    )

  def test_coordinator_globbed_non_test_target(self):
    bfaddr = BuildFileAddress(None, 'bin', 'some/dir')
    result = self.run_coordinator_of_tests(
      address=bfaddr.to_address(),
      bfaddr_to_spec={bfaddr: DescendantAddresses(directory='some/dir')},
      test_target_type=False,
    )
    assert result == AddressAndTestResult(bfaddr.to_address(), None)
