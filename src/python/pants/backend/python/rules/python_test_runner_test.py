# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.inject_init import InjectedInitDigest
from pants.backend.python.rules.pex import CreatePex, Pex
from pants.backend.python.rules.python_test_runner import run_python_test
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEnvironment
from pants.build_graph.address import Address, BuildFileAddress
from pants.engine.fs import EMPTY_SNAPSHOT, Digest, DirectoriesToMerge
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import BuildFileAddresses, HydratedTarget, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.rules.core.core_test_model import Status, TestResult
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.testutil.engine.util import MockGet, run_rule
from pants.testutil.test_base import TestBase


class TestPythonTestRunner(TestBase):

  def test_empty_target_succeeds(self) -> None:
    # NB: Because this particular edge case should early return, we can avoid providing valid
    # mocked yield gets for most of the rule's body. Future tests added to this file will need to
    # provide valid mocks instead.
    unimplemented_mock = lambda _: NotImplemented
    target = PythonTestsAdaptor(address=BuildFileAddress(target_name="target", rel_path="test"))
    result: TestResult = run_rule(
      run_python_test,
      rule_args=[
        target,
        PyTest.global_instance(),
        PythonSetup.global_instance(),
        SubprocessEnvironment.global_instance(),
      ],
      mock_gets=[
        MockGet(
          product_type=SourceRootStrippedSources,
          subject_type=Address,
          mock=lambda _: SourceRootStrippedSources(snapshot=EMPTY_SNAPSHOT),
        ),
        MockGet(
          product_type=TransitiveHydratedTargets,
          subject_type=BuildFileAddresses,
          mock=unimplemented_mock,
        ),
        MockGet(
          product_type=SourceRootStrippedSources,
          subject_type=HydratedTarget,
          mock=unimplemented_mock,
        ),
        MockGet(
          product_type=Digest,
          subject_type=DirectoriesToMerge,
          mock=unimplemented_mock,
        ),
        MockGet(
          product_type=InjectedInitDigest,
          subject_type=Digest,
          mock=unimplemented_mock,
        ),
        MockGet(
          product_type=Pex,
          subject_type=CreatePex,
          mock=unimplemented_mock,
        ),
        MockGet(
          product_type=FallibleExecuteProcessResult,
          subject_type=ExecuteProcessRequest,
          mock=unimplemented_mock,
        ),
      ],
    )
    self.assertEqual(result.status, Status.SUCCESS)
