# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.rules.black import BlackSetup, fmt, lint
from pants.backend.python.rules.pex import Pex
from pants.backend.python.subsystems.black import Black
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEnvironment
from pants.backend.python.targets.formattable_python_target import FormattablePythonTarget
from pants.engine.fs import EMPTY_DIRECTORY_DIGEST
from pants.engine.isolated_process import (
  ExecuteProcessRequest,
  ExecuteProcessResult,
  FallibleExecuteProcessResult,
)
from pants.engine.legacy.structs import TargetAdaptor
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import LintResult
from pants.testutil.engine.util import MockGet, run_rule
from pants.testutil.subsystem.util import global_subsystem_instance
from pants.testutil.test_base import TestBase


class TestPythonTestRunner(TestBase):

  def test_noops_when_disabled(self) -> None:
    black_subsystem = global_subsystem_instance(Black, {Black.options_scope: {"enable": False}})
    target = FormattablePythonTarget(target=TargetAdaptor())
    mock_black_setup = BlackSetup(
      config_path=None,
      merged_input_files=EMPTY_DIRECTORY_DIGEST,
      resolved_requirements_pex=Pex(
        directory_digest=EMPTY_DIRECTORY_DIGEST, output_filename="./fake.pex"
      ),
    )
    rule_args = [
      black_subsystem,
      target,
      mock_black_setup,
      PythonSetup.global_instance(),
      SubprocessEnvironment.global_instance(),
    ]

    fmt_result: FmtResult = run_rule(
      fmt,
      rule_args=rule_args,
      mock_gets=[
        MockGet(
          product_type=ExecuteProcessResult,
          subject_type=ExecuteProcessRequest,
          mock=lambda _: ExecuteProcessResult(
            output_directory_digest=EMPTY_DIRECTORY_DIGEST, stdout=b"bad", stderr=b"bad",
          ),
        )
      ],
    )

    lint_result: LintResult = run_rule(
      lint,
      rule_args=rule_args,
      mock_gets=[
        MockGet(
          product_type=FallibleExecuteProcessResult,
          subject_type=ExecuteProcessRequest,
          mock=lambda _: FallibleExecuteProcessResult(
            stdout=b"bad",
            stderr=b"bad",
            exit_code=127,
            output_directory_digest=EMPTY_DIRECTORY_DIGEST,
          ),
        ),
      ],
    )

    self.assertEqual(fmt_result, FmtResult.noop())
    self.assertEqual(lint_result, LintResult.noop())
