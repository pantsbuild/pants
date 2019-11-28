# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.isolated_process import FallibleExecuteProcessResult
from pants.engine.rules import union
from pants.util.collections import Enum


class Status(Enum):
  SUCCESS = "SUCCESS"
  FAILURE = "FAILURE"


@dataclass(frozen=True)
class TestResult:
  status: Status
  stdout: str
  stderr: str

  # Prevent this class from being detected by pytest as a test class.
  __test__ = False

  @staticmethod
  def from_fallible_execute_process_result(
    process_result: FallibleExecuteProcessResult
  ) -> "TestResult":
    return TestResult(
      status=Status.SUCCESS if process_result.exit_code == 0 else Status.FAILURE,
      stdout=process_result.stdout.decode(),
      stderr=process_result.stderr.decode(),
    )


@union
class TestTarget:
  """A union for registration of a testable target type."""

  # Prevent this class from being detected by pytest as a test class.
  __test__ = False

  @staticmethod
  def non_member_error_message(subject):
    if hasattr(subject, 'address'):
      return f'{subject.address.reference()} is not a testable target.'
    return None
