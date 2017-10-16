# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json

from pants.util.contextutil import temporary_file
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestOptionsQuietIntegration(PantsRunIntegrationTest):
  def test_pants_default_quietness(self):
    pants_run = self.run_pants(['export'])
    self.assert_success(pants_run)
    json.loads(pants_run.stdout_data)

  def test_pants_no_quiet_cli(self):
    pants_run = self.run_pants(['--no-quiet', 'export'])
    self.assert_success(pants_run)

    # Since pants progress will show up in stdout, therefore, json parsing should fail.
    with self.assertRaises(ValueError):
      json.loads(pants_run.stdout_data)

  def test_pants_no_quiet_env(self):
    pants_run = self.run_pants(['export'], extra_env={'PANTS_QUIET': 'FALSE'})
    self.assert_success(pants_run)

    # Since pants progress will show up in stdout, therefore, json parsing should fail.
    with self.assertRaises(ValueError):
      json.loads(pants_run.stdout_data)

  def test_pants_no_quiet_output_file(self):
    with temporary_file() as f:
      pants_run = self.run_pants(['--no-quiet', 'export', '--output-file={}'.format(f.name)])
      self.assert_success(pants_run)

      json_string = f.read()
      # Make sure the json is valid from the file read.
      json.loads(json_string)
      # Make sure json string does not appear in stdout.
      self.assertNotIn(json_string, pants_run.stdout_data)
