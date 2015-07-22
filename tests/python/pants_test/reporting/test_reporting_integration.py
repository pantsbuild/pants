# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os.path
import re
import unittest

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


_HEADER = 'invocation_id,task_name,targets_hash,target_id,cache_key_id,cache_key_hash,phase,valid\n'
_REPORT_LOCATION = 'reports/latest/invalidation-report.csv'

_ENTRY = re.compile(ur'^\d+,\S+,(init|pre-check|post-check),(True|False)')
_INIT = re.compile(ur'^\d+,JavaCompile,\w+,\S+,init,(True|False)')
_POST = re.compile(ur'^\d+,JavaCompile,\w+,\S+,post-check,(True|False)')
_PRE = re.compile(ur'^\d+,JavaCompile,\w+,\S+,pre-check,(True|False)')


class TestReportingIntegrationTest(PantsRunIntegrationTest, unittest.TestCase):

  def test_invalidation_report_output(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      command = ['compile',
                 'examples/src/java/org/pantsbuild/example/hello/main',
                 '--reporting-invalidation-report']
      pants_run = self.run_pants_with_workdir(command, workdir)
      self.assert_success(pants_run)
      output = os.path.join(workdir, _REPORT_LOCATION)
      self.assertTrue(os.path.exists(output))
      with open(output) as f:
        self.assertEqual(_HEADER, f.readline())
        for line in f.readlines():
          self.assertTrue(_ENTRY.match(line))
          if _INIT.match(line):
            init = True
          elif _PRE.match(line):
            pre = True
          elif _POST.match(line):
            post = True
        self.assertTrue(init and pre and post)

  def test_ouput_no_suppression(self):
    command = ['clean-all', 'compile', '--compile-java-strategy=isolated',
               'testprojects/src/java/org/pantsbuild/testproject/reporting_example:main']
    pants_run = self.run_pants(command)
    self.assert_failure(pants_run, msg='error: unreported exception')
    self.assertTrue('mandatory_warning: unchecked cast' in pants_run.stdout_data)

  def test_output_with_suppression(self):
    command = ['clean-all', 'compile', '--compile-java-strategy=isolated',
               'testprojects/src/java/org/pantsbuild/testproject/reporting_example:main',
               '--compile-java-level=warn']
    pants_run = self.run_pants(command)
    self.assert_failure(pants_run, msg='error: unreported exception')
    self.assertFalse('mandatory_warning: unchecked cast' in pants_run.stdout_data)
