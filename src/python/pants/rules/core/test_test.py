# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from textwrap import dedent
from typing import Dict, Optional

from pants.base.specs import DescendantAddresses, SingleAddress, Spec
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.addressable import BuildFileAddresses
from pants.engine.build_files import AddressOriginMap
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, FileContent, InputFilesContent, Snapshot
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.legacy.structs import PythonBinaryAdaptor, PythonTestsAdaptor
from pants.engine.rules import UnionMembership
from pants.rules.core.test import (
  AddressAndDebugRequest,
  AddressAndTestResult,
  Status,
  TestDebugRequest,
  TestResult,
  TestTarget,
  coordinator_of_tests,
  run_tests,
)
from pants.source.wrapped_globs import EagerFilesetWithSpec
from pants.testutil.engine.util import MockConsole, MockGet, MockOptions, run_rule
from pants.testutil.test_base import TestBase


class TestTest(TestBase):
  def make_ipr(self, content: bytes) -> InteractiveProcessRequest:
    input_files_content = InputFilesContent((
      FileContent(path='program.py', content=content, is_executable=True),
    ))
    digest = self.request_single_product(Digest, input_files_content)
    return InteractiveProcessRequest(
      argv=("/usr/bin/python", "program.py",),
      run_in_workspace=False,
      input_files=digest,
    )

  def make_successful_ipr(self) -> InteractiveProcessRequest:
    content = b"import sys; sys.exit(0)"
    return self.make_ipr(content)

  def make_failure_ipr(self) -> InteractiveProcessRequest:
    content = b"import sys; sys.exit(1)"
    return self.make_ipr(content)

  def single_target_test(self, result, expected_console_output, success=True, debug=False):
    console = MockConsole(use_colors=False)
    options = MockOptions(debug=debug)
    runner = InteractiveRunner(self.scheduler)
    addr = self.make_build_target_address("some/target")
    res = run_rule(
      run_tests,
      rule_args=[console, options, runner, BuildFileAddresses([addr])],
      mock_gets=[
        MockGet(
          product_type=AddressAndTestResult,
          subject_type=Address,
          mock=lambda _: AddressAndTestResult(addr, result),
        ),
        MockGet(
          product_type=AddressAndDebugRequest,
          subject_type=Address,
          mock=lambda _: AddressAndDebugRequest(addr, TestDebugRequest(ipr=self.make_successful_ipr() if success else self.make_failure_ipr()))
        ),
        MockGet(
          product_type=BuildFileAddress,
          subject_type=BuildFileAddresses,
          mock=lambda bfas: bfas.dependencies[0],
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
    options = MockOptions(debug=False)
    runner = InteractiveRunner(self.scheduler)
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

    def make_debug_request(target):
      request = TestDebugRequest(ipr=self.make_successful_ipr() if target == target1 else self.make_failure_ipr())
      return AddressAndDebugRequest(target, request)

    res = run_rule(
      run_tests,
      rule_args=[console, options, runner, (target1, target2)],
      mock_gets=[
        MockGet(product_type=AddressAndTestResult, subject_type=Address, mock=make_result),
        MockGet(product_type=AddressAndDebugRequest, subject_type=Address, mock=make_debug_request),
        MockGet(
          product_type=BuildFileAddress,
          subject_type=BuildFileAddresses,
          mock=lambda tgt: BuildFileAddress(
            rel_path=f'{tgt.spec_path}/BUILD', target_name=tgt.target_name,
          )
        ),
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

  def test_debug_options(self):
    self.single_target_test(
      result=None,
      expected_console_output='',
      success=False,
      debug=True
    )

  def run_coordinator_of_tests(
    self,
    *,
    address: Address,
    bfaddr_to_origin: Optional[Dict[BuildFileAddress, Spec]] = None,
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
        files=tuple(["test.py"] if include_sources else []),
        dirs=()
      )
    )
    target_adaptor = (
      PythonTestsAdaptor(type_alias='python_tests', sources=mocked_fileset)
      if test_target_type else
      PythonBinaryAdaptor(type_alias='python_binary', sources=mocked_fileset)
    )
    with self.captured_logging(logging.INFO):
      result: AddressAndTestResult = run_rule(
        coordinator_of_tests,
        rule_args=[
          HydratedTarget(address, target_adaptor, ()),
          UnionMembership(union_rules={TestTarget: [PythonTestsAdaptor]}),
          AddressOriginMap(bfaddr_to_origin=bfaddr_to_origin or {}),
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
        bfaddr_to_origin={bfaddr: SingleAddress(directory='some/dir', name='bin')},
        test_target_type=False,
      )

  def test_coordinator_empty_sources(self):
    addr = Address.parse("some/target")
    result = self.run_coordinator_of_tests(address=addr, include_sources=False)
    assert result == AddressAndTestResult(addr, None)

  def test_coordinator_globbed_test_target(self):
    bfaddr = BuildFileAddress(rel_path='some/dir', target_name='tests')
    result = self.run_coordinator_of_tests(
      address=bfaddr.to_address(),
      bfaddr_to_origin={bfaddr: DescendantAddresses(directory='some/dir')}
    )
    assert result == AddressAndTestResult(
      bfaddr.to_address(), TestResult(status=Status.SUCCESS, stdout='foo', stderr='')
    )

  def test_coordinator_globbed_non_test_target(self):
    bfaddr = BuildFileAddress(rel_path='some/dir', target_name='bin')
    result = self.run_coordinator_of_tests(
      address=bfaddr.to_address(),
      bfaddr_to_origin={bfaddr: DescendantAddresses(directory='some/dir')},
      test_target_type=False,
    )
    assert result == AddressAndTestResult(bfaddr.to_address(), None)
