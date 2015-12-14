# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestJvmDependencyUsageIntegration(PantsRunIntegrationTest):

  def _run_dep_usage(self, workdir, target, clean_all=False, extra_args=None):
    with temporary_dir() as outdir:
      outfile = os.path.join(outdir, 'out.json')
      args = [
          'dep-usage',
          target,
          '--dep-usage-jvm-output-file={}'.format(outfile),
          ] + (extra_args if extra_args else [])
      if clean_all:
        args.insert(0, 'clean-all')

      # Run, and then parse the report from json.
      self.assert_success(self.run_pants_with_workdir(args, workdir))
      with open(outfile) as f:
        return json.load(f)

  def _assert_non_zero_usage(self, dep_usage_json):
    for entry in dep_usage_json:
      self.assertGreater(entry['max_usage'], 0.0, 'Usage was 0.0 in: `{}`'.format(entry))

  def test_dep_usage(self):
    target = 'testprojects/src/java/org/pantsbuild/testproject/unicode/main'
    with self.temporary_workdir() as workdir:
      # Run twice.
      run_one = self._run_dep_usage(workdir, target, clean_all=True)
      run_two = self._run_dep_usage(workdir, target, clean_all=False)

      # Confirm that usage is non-zero, and that the reports match.
      self._assert_non_zero_usage(run_two)
      self.assertEquals(run_one, run_two)
