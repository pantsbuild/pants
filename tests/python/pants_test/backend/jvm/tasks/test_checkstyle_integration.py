# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

import pytest

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_cached


class CheckstyleIntegrationTest(PantsRunIntegrationTest):

  @pytest.mark.xfail
  # This test is now expected to fail due to changes in caching behaviour.
  # TODO(Tansy Arron): Write a general purpose incremental compile test.
  # https://github.com/pantsbuild/pants/issues/2591
  def test_checkstyle_cached(self):
    with self.temporary_cachedir() as cache:
      with self.temporary_workdir() as workdir:
        args = [
            'clean-all',
            'compile.checkstyle',
            "--cache-write-to=['{}']".format(cache),
            "--cache-read-from=['{}']".format(cache),
            'examples/tests/java/org/pantsbuild/example/hello/greet',
            '-ldebug'
          ]

        pants_run = self.run_pants_with_workdir(args, workdir)
        self.assert_success(pants_run)
        self.assertIn('abc_Checkstyle_compile_checkstyle will write to local artifact cache',
            pants_run.stdout_data)

        pants_run = self.run_pants_with_workdir(args, workdir)
        self.assert_success(pants_run)
        self.assertIn('abc_Checkstyle_compile_checkstyle will read from local artifact cache',
            pants_run.stdout_data)
        # Make sure we are *only* reading from the cache and not also writing,
        # implying there was as a cache hit.
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
    with self.temporary_workdir() as workdir:
      with temporary_dir() as tmp:
        configs = [
            dedent("""
              <module name="TreeWalker">
                <property name="tabWidth" value="2"/>
              </module>"""),
            dedent("""
              <module name="TreeWalker">
                <module name="LineLength">
                  <property name="max" value="100"/>
                </module>
              </module>""")
          ]

        for config in configs:
          # Ensure that even though the config files have the same name, their
          # contents will invalidate the targets.
          config_file = os.path.join(tmp, 'config.xml')
          self._create_config_file(config_file, config)
          args = [
              'clean-all',
              'compile.checkstyle',
              cache_args,
              'examples/src/java/org/pantsbuild/example/hello/simple',
              '--compile-checkstyle-configuration={}'.format(config_file)
            ]
          pants_run = self.run_pants_with_workdir(args, workdir)
          self.assert_success(pants_run)

  @ensure_cached(expected_num_artifacts=2)
  def test_jvm_tool_changes_invalidate_targets(self, cache_args):
    with self.temporary_workdir() as workdir:
      # Ensure that only the second use of the default checkstyle will not invalidate anything.
      for checkstyle_jar in (None, 'testprojects/3rdparty/checkstyle', None):
        args = [
            'compile.checkstyle',
            cache_args,
            '--checkstyle={}'.format(checkstyle_jar) if checkstyle_jar else '',
            'examples/src/java/org/pantsbuild/example/hello/simple'
          ]
        pants_run = self.run_pants_with_workdir(args, workdir)
        print(pants_run.stdout_data)
        self.assert_success(pants_run)
