# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.download_pex_bin import download_pex_bin
from pants.backend.python.rules.inject_init import inject_init
from pants.backend.python.rules.pex import CreatePex, create_pex
from pants.backend.python.rules.python_test_runner import run_python_test
from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.subsystems.python_native_code import (
  PythonNativeCode,
  create_pex_native_build_environment,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import (
  SubprocessEnvironment,
  create_subprocess_encoding_environment,
)
from pants.engine.legacy.structs import PythonTestsAdaptor
from pants.engine.rules import RootRule
from pants.engine.selectors import Params
from pants.rules.core.core_test_model import Status, TestResult
from pants.rules.core.strip_source_root import strip_source_root
from pants.source.source_root import SourceRootConfig
from pants.testutil.subsystem.util import init_subsystems
from pants.testutil.test_base import TestBase
from pants.util.collections import assert_single_element


class TestPythonTestRunner(TestBase):

  @classmethod
  def rules(cls):
    return super().rules() + [
      run_python_test,
      create_pex,
      strip_source_root,
      inject_init,
      create_pex_native_build_environment,
      create_subprocess_encoding_environment,
      download_pex_bin,
      RootRule(PythonTestsAdaptor),
      RootRule(CreatePex),
      RootRule(PyTest),
      RootRule(PythonSetup),
      RootRule(PythonNativeCode),
      RootRule(SubprocessEnvironment),
      RootRule(SourceRootConfig),
    ]

  def setUp(self):
    super().setUp()
    init_subsystems([
      PythonSetup, PythonNativeCode, SubprocessEnvironment, PyTest, SourceRootConfig
    ])

  def run_pytest(self, target: PythonTestsAdaptor) -> TestResult:
    return assert_single_element(
      self.scheduler.product_request(TestResult, [Params(
        target,
        PyTest.global_instance(),
        PythonSetup.global_instance(),
        SubprocessEnvironment.global_instance(),
        PythonNativeCode.global_instance(),
        SourceRootConfig.global_instance(),
      )])
    )

  def test_empty_target_succeeds(self) -> None:
    result = self.run_pytest(target=PythonTestsAdaptor(name="test", sources=[]))
    self.assertEqual(result.status, Status.SUCCESS)
