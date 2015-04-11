# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from mock import MagicMock, patch

from pants.goal.run_tracker import RunTracker
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest


class RunTrackerTest(BaseTest):
  def test_run_tracker(self):
    with temporary_dir() as info_dir:
      tracker = RunTracker(info_dir, unbuffered_workunits=['morx'])
      tracker.start(MagicMock())
      with tracker.new_workunit('morx') as workunit:
        self.assertEqual(sys.stdout, workunit.output('stdout'))
      with tracker.new_workunit('fleem') as workunit:
        self.assertNotEqual(sys.stdout, workunit.output('stdout'))
