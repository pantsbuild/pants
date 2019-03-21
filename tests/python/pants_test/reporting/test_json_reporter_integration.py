# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import unittest

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class JsonReporterIntegrationTest(PantsRunIntegrationTest, unittest.TestCase):
  def test_json_report_generated(self):
    with temporary_dir() as temp_dir:
      command = ['list',
                 'examples/src/java/org/pantsbuild/example/hello/main',
                 '--reporting-reports-dir={}'.format(temp_dir)]

      pants_run = self.run_pants(command)
      self.assert_success(pants_run)

      output = os.path.join(temp_dir, 'latest', 'json', 'build.json')
      self.assertTrue(os.path.exists(output))

      parsed_report = json.loads(open(output).read())
      self.assertIsInstance(parsed_report['workunits'], dict)
