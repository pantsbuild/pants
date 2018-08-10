# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class SchedulerIntegrationTest(PantsRunIntegrationTest):

  def test_visualize_to(self):
    # Tests usage of the `--native-engine-visualize-to=` option, which triggers background
    # visualization of the graph. There are unit tests confirming the content of the rendered
    # results.
    with temporary_dir() as destdir:
      args = [
          '--native-engine-visualize-to={}'.format(destdir),
          'list',
          'examples/src/scala/org/pantsbuild/example/hello/welcome',
        ]
      self.assert_success(self.run_pants(args))
      self.assertTrue(len(os.listdir(destdir)) > 0)
