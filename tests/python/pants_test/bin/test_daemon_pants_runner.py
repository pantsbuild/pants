# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).



from unittest.mock import Mock, patch

from contextlib2 import contextmanager

from pants.base.exiter import PANTS_FAILED_EXIT_CODE
from pants.bin.daemon_pants_runner import (DaemonPantsRunner, _PantsProductPrecomputeFailed,
                                           _PantsRunFinishedWithFailureException)
from pants.bin.local_pants_runner import LocalPantsRunner
from pants_test.test_base import TestBase


class DaemonPantsRunnerTest(TestBase):

  def setUp(self):
    self.mock_sock = Mock()

    self.mock_nailgunned_stdio = Mock()
    self.mock_nailgunned_stdio.return_value.__enter__ = Mock()
    self.mock_nailgunned_stdio.return_value.__exit__ = Mock()

  def __create_mock_exiter(self):
    mock_exiter = Mock()
    mock_exiter.exit = Mock()
    return mock_exiter

  @contextmanager
  def enable_creating_dpr(self):
    with patch.object(LocalPantsRunner, 'parse_options', Mock(return_value=(Mock(), Mock(), Mock()))):
      yield

  def test_precompute_exceptions_propagated(self):
    """
    Test that exceptions raised at precompute time are propagated correctly.

    May become obsolete after #8002 is resolved.
    """
    raising_scheduler_service = Mock()
    raising_scheduler_service.prefork = Mock(side_effect=Exception('I called prefork'))

    with self.enable_creating_dpr():
      dpr = DaemonPantsRunner.create(
        sock=self.mock_sock,
        args=[],
        env={},
        services={},
        scheduler_service=raising_scheduler_service
      )

      self.assertEqual(
        repr(dpr._exception),
        repr(_PantsProductPrecomputeFailed(Exception('I called prefork')))
      )

      self.check_runs_exit_with_code(dpr, PANTS_FAILED_EXIT_CODE)

  def test_precompute_propagates_failures(self):
    """
    Tests that, when precompute returns a non-zero exit code (but doesn't raise exceptions),
    it will be propagated to the end of the run.

    May become obsolete after #8002 is resolved.
    """
    weird_return_value = 19

    non_zero_returning_scheduler_service = Mock()
    non_zero_returning_scheduler_service.prefork = Mock(
      return_value=(-1, -1, weird_return_value)
    )

    with self.enable_creating_dpr():
      dpr = DaemonPantsRunner.create(
        sock=self.mock_sock,
        args=[],
        env={},
        services={},
        scheduler_service=non_zero_returning_scheduler_service
      )

      self.assertEqual(
        repr(dpr._exception),
        repr(_PantsProductPrecomputeFailed(_PantsRunFinishedWithFailureException(exit_code=weird_return_value)))
      )

      self.check_runs_exit_with_code(dpr, weird_return_value)

  def check_runs_exit_with_code(self, daemon_pants_runner, code):
    with patch.object(DaemonPantsRunner, 'nailgunned_stdio', self.mock_nailgunned_stdio):
      daemon_pants_runner._exiter = self.__create_mock_exiter()
      daemon_pants_runner.run()
      self.assertIs(daemon_pants_runner._exiter.exit.called, True)
      self.assertEqual(daemon_pants_runner._exiter.exit.call_args[0][0], code)
