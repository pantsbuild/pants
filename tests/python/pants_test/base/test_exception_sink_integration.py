# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ExceptionSinkIntegrationTest(PantsRunIntegrationTest):
  def test_dumps_traceback_on_fatal_signal(self):
    """???"""

  def test_logs_unhandled_exception(self):
    """???"""

  def test_reset_exiter(self):
    """???"""

  def test_reset_interactive_output_stream(self):
    """???"""
