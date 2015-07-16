# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_cached


class CheckstyleIntegrationTest(PantsRunIntegrationTest):
  def test_checkstyle_cached(self):
    with temporary_dir(root_dir=self.workdir_root()) as cache:
      checkstyle_args = [
          'clean-all',
          'compile.checkstyle',
          "--cache-write-to=['{}']".format(cache),
          "--cache-read-from=['{}']".format(cache),
          'examples/tests/java/org/pantsbuild/example/hello/greet',
          '-ldebug'
        ]

      with temporary_dir(root_dir=self.workdir_root()) as workdir:
        pants_run = self.run_pants_with_workdir(checkstyle_args, workdir)
        self.assert_success(pants_run)
        self.assertIn('abc_Checkstyle_compile_checkstyle will write to local artifact cache',
            pants_run.stdout_data)

      with temporary_dir(root_dir=self.workdir_root()) as workdir:
        pants_run = self.run_pants_with_workdir(checkstyle_args, workdir)
        self.assert_success(pants_run)
        self.assertIn('abc_Checkstyle_compile_checkstyle will read from local artifact cache',
            pants_run.stdout_data)
        # make sure we are *only* reading from the cache and not also writing,
        # implying there was as a cache hit
        self.assertNotIn('abc_Checkstyle_compile_checkstyle will write to local artifact cache',
            pants_run.stdout_data)

  def _create_config_file(self, filepath, rules_xml=''):
    with open(filepath, 'w') as f:
      f.write(dedent(
        """<?xml version="1.0"?>
           <!DOCTYPE module PUBLIC
             "-//Puppy Crawl//DTD Check Configuration 1.3//EN"
             "http://www.puppycrawl.com/dtds/configuration_1_3.dtd">
           <module name="Checker">
             {rules_xml}
           </module>""".format(rules_xml=rules_xml)))

  @ensure_cached(expected_num_artifacts=2)
  def test_config_invalidates_targets(self, cache_args):
    with temporary_dir(root_dir=self.workdir_root()) as tmp:

      tab_width_checker = os.path.join(tmp, 'tab_width_checker.xml')
      self._create_config_file(tab_width_checker, dedent("""
          <module name="TreeWalker">
            <property name="tabWidth" value="2"/>
          </module>
        """))

      line_length_checker = os.path.join(tmp, 'line_length_checker.xml')
      self._create_config_file(line_length_checker, dedent("""
          <module name="TreeWalker">
            <module name="LineLength">
              <property name="max" value="100"/>
            </module>
          </module>
        """))

      checkstyle_args = [
        'clean-all',
        'compile.checkstyle',
        cache_args,
        'examples/src/java/org/pantsbuild/example/hello/simple'
      ]

      with open(tab_width_checker, 'r') as f:
        print(f.read())

      for config in (tab_width_checker, line_length_checker):
        pants_run = self.run_pants(checkstyle_args + ['--compile-checkstyle-configuration={}'.format(config)])
        self.assert_success(pants_run)

  @ensure_cached(expected_num_artifacts=2)
  def test_jvm_tool_changes_invalidate_targets(self, cache_args):
    for checkstyle_jar in ('//:checkstyle', 'testprojects/3rdparty/checkstyle', '//:checkstyle'):
      args = [
        'compile.checkstyle',
        cache_args,
        '--checkstyle=["{}"]'.format(checkstyle_jar),
        'examples/src/java/org/pantsbuild/example/hello/simple'
      ]
      pants_run = self.run_pants(args)
      self.assert_success(pants_run)
