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
_INIT = re.compile(ur'^\d+,JmakeCompile,\w+,\S+,init,(True|False)')
_POST = re.compile(ur'^\d+,JmakeCompile,\w+,\S+,post-check,(True|False)')
_PRE = re.compile(ur'^\d+,JmakeCompile,\w+,\S+,pre-check,(True|False)')


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

  INFO_LEVEL_COMPILE_MSG='Compiling 1 java source in 1 target (examples/src/java/org/pantsbuild/example/hello/simple:simple).'
  DEBUG_LEVEL_COMPILE_MSG='compile(examples/src/java/org/pantsbuild/example/hello/simple:simple) finished with status Successful'

  def test_ouput_level_warn(self):
    command = ['compile', '--compile-java-strategy=isolated',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-java-level=warn']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertFalse(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
    self.assertFalse(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

  def test_output_level_info(self):
    command = ['compile', '--compile-java-strategy=isolated',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-java-level=info']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertTrue(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
    self.assertFalse(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

  def test_output_level_debug(self):
    command = ['compile', '--compile-java-strategy=isolated',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-java-level=debug']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertTrue(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
    self.assertTrue(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)

  def test_output_color_enabled(self):
    command = ['compile', '--compile-java-strategy=isolated',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-java-colors']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertTrue(self.INFO_LEVEL_COMPILE_MSG + '\x1b[0m' in pants_run.stdout_data)

  def test_output_level_group_compile(self):
    """Set level with the scope 'compile' and see that it propagates to the task level."""
    command = ['compile', '--compile-java-strategy=isolated',
               'examples/src/java/org/pantsbuild/example/hello/simple',
               '--compile-level=debug']
    pants_run = self.run_pants(command)
    self.assert_success(pants_run)
    self.assertTrue(self.INFO_LEVEL_COMPILE_MSG in pants_run.stdout_data)
    self.assertTrue(self.DEBUG_LEVEL_COMPILE_MSG in pants_run.stdout_data)
