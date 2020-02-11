# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from textwrap import dedent
from typing import Optional
from unittest.mock import Mock

from pants.base.specs import DescendantAddresses, OriginSpec, SingleAddress
from pants.build_graph.address import Address
from pants.engine.addressable import AddressesWithOrigins, AddressWithOrigin
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST, Digest, FileContent, InputFilesContent, Snapshot
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.legacy.graph import HydratedTarget, HydratedTargetWithOrigin
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
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase


class MockOptions:
  def __init__(self, **values):
    self.values = Mock(**values)


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

  @staticmethod
  def make_addresses_with_origins(*addresses: Address) -> AddressesWithOrigins:
    return AddressesWithOrigins([
      AddressWithOrigin(
        address=address,
        origin=SingleAddress(directory=address.spec_path, name=address.target_name)
      ) for address in addresses
    ])

  def single_target_test(self, result, expected_console_output, success=True, debug=False):
    console = MockConsole(use_colors=False)
    options = MockOptions(debug=debug)
    runner = InteractiveRunner(self.scheduler)
    addr = Address.parse("some/target")
    res = run_rule(
      run_tests,
      rule_args=[console, options, runner, self.make_addresses_with_origins(addr)],
      mock_gets=[
        MockGet(
          product_type=AddressAndTestResult,
          subject_type=AddressWithOrigin,
          mock=lambda _: AddressAndTestResult(addr, result),
        ),
        MockGet(
          product_type=AddressAndDebugRequest,
          subject_type=AddressWithOrigin,
          mock=lambda _: AddressAndDebugRequest(
            addr,
            TestDebugRequest(ipr=self.make_successful_ipr() if success else self.make_failure_ipr())
          )
        ),
      ],
    )
    assert console.stdout.getvalue() == expected_console_output
    assert (0 if success else 1) == res.exit_code

  def test_output_success(self) -> None:
    self.single_target_test(
      result=TestResult(status=Status.SUCCESS, stdout='Here is some output from a test', stderr=''),
      expected_console_output=dedent("""\
        some/target stdout:
        Here is some output from a test

        some/target                                                                     .....   SUCCESS
      """),
    )

  def test_output_failure(self) -> None:
    self.single_target_test(
      result=TestResult(status=Status.FAILURE, stdout='Here is some output from a test', stderr=''),
      expected_console_output=dedent("""\
        some/target stdout:
        Here is some output from a test

        some/target                                                                     .....   FAILURE
        """),
      success=False,
    )

  def test_output_mixed(self) -> None:
    console = MockConsole(use_colors=False)
    options = MockOptions(debug=False)
    runner = InteractiveRunner(self.scheduler)
    address1 = Address.parse("testprojects/tests/python/pants/passes")
    address2 = Address.parse("testprojects/tests/python/pants/fails")

    def make_result(address_with_origin: AddressWithOrigin) -> AddressAndTestResult:
      address = address_with_origin.address
      if address == address1:
        tr = TestResult(status=Status.SUCCESS, stdout='I passed\n', stderr='')
      elif address == address2:
        tr = TestResult(status=Status.FAILURE, stdout='I failed\n', stderr='')
      else:
        raise Exception("Unrecognised target")
      return AddressAndTestResult(address, tr)

    def make_debug_request(address_with_origin: AddressWithOrigin) -> AddressAndDebugRequest:
      address = address_with_origin.address
      request = TestDebugRequest(
        ipr=self.make_successful_ipr() if address == address1 else self.make_failure_ipr()
      )
      return AddressAndDebugRequest(address, request)

    res = run_rule(
      run_tests,
      rule_args=[console, options, runner, self.make_addresses_with_origins(address1, address2)],
      mock_gets=[
        MockGet(
          product_type=AddressAndTestResult, subject_type=AddressWithOrigin, mock=make_result
        ),
        MockGet(
          product_type=AddressAndDebugRequest,
          subject_type=AddressWithOrigin,
          mock=make_debug_request
        ),
      ],
    )

    self.assertEqual(1, res.exit_code)
    self.assertEqual(console.stdout.getvalue(), dedent("""\
      testprojects/tests/python/pants/passes stdout:
      I passed

      testprojects/tests/python/pants/fails stdout:
      I failed


      testprojects/tests/python/pants/passes                                          .....   SUCCESS
      testprojects/tests/python/pants/fails                                           .....   FAILURE
      """))

  def test_stderr(self) -> None:
    self.single_target_test(
      result=TestResult(status=Status.FAILURE, stdout='', stderr='Failure running the tests!'),
      expected_console_output=dedent("""\
        some/target stderr:
        Failure running the tests!

        some/target                                                                     .....   FAILURE
        """),
      success=False,
    )

  def test_debug_options(self) -> None:
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
    origin: Optional[OriginSpec] = None,
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
          HydratedTargetWithOrigin(
            target=HydratedTarget(address, target_adaptor, ()),
            origin=origin or SingleAddress(directory=address.spec_path, name=address.target_name),
          ),
          UnionMembership(union_rules={TestTarget: [PythonTestsAdaptor]}),
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

  def test_coordinator_single_test_target(self) -> None:
    addr = Address.parse("some/dir:tests")
    result = self.run_coordinator_of_tests(address=addr)
    assert result == AddressAndTestResult(
      addr, TestResult(status=Status.SUCCESS, stdout='foo', stderr='')
    )

  def test_coordinator_single_non_test_target(self) -> None:
    addr = Address.parse("some/dir:bin")
    # Note that this is not the same error message the end user will see, as we're resolving
    # union Get requests in run_rule, not the real engine.  But this test still asserts that
    # we error when we expect to error.
    with self.assertRaisesRegex(AssertionError, r'Rule requested: .* which cannot be satisfied.'):
      self.run_coordinator_of_tests(
        address=addr,
        origin=SingleAddress(directory='some/dir', name='bin'),
        test_target_type=False,
      )

  def test_coordinator_empty_sources(self) -> None:
    addr = Address.parse("some/dir:tests")
    result = self.run_coordinator_of_tests(address=addr, include_sources=False)
    assert result == AddressAndTestResult(addr, None)

  def test_coordinator_globbed_test_target(self) -> None:
    addr = Address.parse("some/dir:tests")
    result = self.run_coordinator_of_tests(
      address=addr, origin=DescendantAddresses(directory='some/dir'),
    )
    assert result == AddressAndTestResult(
      addr, TestResult(status=Status.SUCCESS, stdout='foo', stderr='')
    )

  def test_coordinator_globbed_non_test_target(self) -> None:
    addr = Address.parse("some/dir:bin")
    result = self.run_coordinator_of_tests(
      address=addr,
      origin=DescendantAddresses(directory='some/dir'),
      test_target_type=False,
    )
    assert result == AddressAndTestResult(addr, None)
