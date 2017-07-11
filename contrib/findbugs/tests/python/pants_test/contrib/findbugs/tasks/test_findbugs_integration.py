# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_file
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class FindBugsTest(PantsRunIntegrationTest):

  @classmethod
  def hermetic(cls):
    return True

  def run_pants(self, command, config=None, stdin_data=None, extra_env=None, **kwargs):
    full_config = {
      'GLOBAL': {
        'pythonpath': ["%(buildroot)s/contrib/findbugs/src/python"],
        'backend_packages': ["pants.backend.codegen", "pants.backend.jvm", "pants.contrib.findbugs"]
      }
    }
    if config:
      for scope, scoped_cfgs in config.items():
        updated = full_config.get(scope, {})
        updated.update(scoped_cfgs)
        full_config[scope] = updated
    return super(FindBugsTest, self).run_pants(command, full_config, stdin_data, extra_env, **kwargs)

  def test_no_warnings(self):
    cmd = ['compile', 'contrib/findbugs/tests/java/org/pantsbuild/contrib/findbugs:none']
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertNotIn('Bug', pants_run.stdout_data)
    self.assertNotIn('Errors:', pants_run.stdout_data)

  def test_empty_source_file(self):
    cmd = ['compile', 'contrib/findbugs/tests/java/org/pantsbuild/contrib/findbugs:empty']
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertNotIn('Bug', pants_run.stdout_data)
    self.assertNotIn('Errors:', pants_run.stdout_data)

  def test_low_warning(self):
    cmd = ['compile', 'contrib/findbugs/tests/java/org/pantsbuild/contrib/findbugs:low']
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertIn('Bug[low]: VA_FORMAT_STRING_USES_NEWLINE Format string', pants_run.stdout_data)
    self.assertNotIn('Errors:', pants_run.stdout_data)
    self.assertIn('Bugs: 1 (High: 0, Normal: 0, Low: 1)', pants_run.stdout_data)

  def test_all_warnings(self):
    cmd = ['compile', 'contrib/findbugs/tests/java/org/pantsbuild/contrib/findbugs::']
    pants_run = self.run_pants(cmd)
    self.assert_success(pants_run)
    self.assertIn('Bug[high]: EC_UNRELATED_TYPES', pants_run.stdout_data)
    self.assertIn('Bug[normal]: NP_ALWAYS_NULL', pants_run.stdout_data)
    self.assertIn('Bug[low]: VA_FORMAT_STRING_USES_NEWLINE', pants_run.stdout_data)
    self.assertNotIn('Errors:', pants_run.stdout_data)
    self.assertIn('Bugs: 3 (High: 1, Normal: 1, Low: 1)', pants_run.stdout_data)

  def test_max_rank_fail_on_error(self):
    cmd = ['compile', 'contrib/findbugs/tests/java/org/pantsbuild/contrib/findbugs::']
    pants_ini_config = {'compile.findbugs': {'max_rank': 9, 'fail_on_error': True}}
    pants_run = self.run_pants(cmd, config=pants_ini_config)
    self.assert_failure(pants_run)
    self.assertIn('Bug[high]:', pants_run.stdout_data)
    self.assertIn('Bug[normal]:', pants_run.stdout_data)
    self.assertNotIn('Bug[low]:', pants_run.stdout_data)
    self.assertIn('FAILURE: failed with 2 bugs and 0 errors', pants_run.stdout_data)

  def test_exclude(self):
    cmd = ['compile', 'contrib/findbugs/tests/java/org/pantsbuild/contrib/findbugs::']
    with temporary_file(root_dir=get_buildroot()) as exclude_file:
      exclude_file.write(dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <FindBugsFilter>
          <Match>
            <Bug pattern="NP_ALWAYS_NULL" />
            <Class name="org.pantsbuild.contrib.findbugs.NormalWarning" />
            <Method name="main" />
          </Match>
        </FindBugsFilter>
      """))
      exclude_file.close()
      pants_ini_config = {'compile.findbugs': {'exclude_filter_file': exclude_file.name}}
      pants_run = self.run_pants(cmd, config=pants_ini_config)
    self.assert_success(pants_run)
    self.assertIn('Bug[high]:', pants_run.stdout_data)
    self.assertNotIn('Bug[normal]:', pants_run.stdout_data)
    self.assertIn('Bug[low]:', pants_run.stdout_data)
    self.assertNotIn('Errors:', pants_run.stdout_data)
    self.assertIn('Bugs: 2 (High: 1, Normal: 0, Low: 1)', pants_run.stdout_data)

  def test_error(self):
    cmd = ['compile', 'contrib/findbugs/tests/java/org/pantsbuild/contrib/findbugs:high']
    with temporary_file(root_dir=get_buildroot()) as exclude_file:
      exclude_file.write(dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <FindBugsFilter>
          <Incomplete Tag
        </FindBugsFilter>
      """))
      exclude_file.close()
      pants_ini_config = {'compile.findbugs': {'exclude_filter_file': exclude_file.name}}
      pants_run = self.run_pants(cmd, config=pants_ini_config)
    self.assert_success(pants_run)
    self.assertIn('Bug[high]:', pants_run.stdout_data)
    self.assertNotIn('Bug[normal]:', pants_run.stdout_data)
    self.assertNotIn('Bug[low]:', pants_run.stdout_data)
    self.assertIn('Errors: 1', pants_run.stdout_data)
    self.assertIn('Unable to read filter:', pants_run.stdout_data)
    self.assertIn('Attribute name "Tag" associated with an element type', pants_run.stdout_data)
    self.assertIn('Bugs: 1 (High: 1, Normal: 0, Low: 0)', pants_run.stdout_data)

  def test_transitive(self):
    cmd = ['compile', 'contrib/findbugs/tests/java/org/pantsbuild/contrib/findbugs:all']
    pants_ini_config = {'compile.findbugs': {'transitive': True}}
    pants_run = self.run_pants(cmd, config=pants_ini_config)
    self.assert_success(pants_run)
    self.assertIn('Bug[high]: EC_UNRELATED_TYPES', pants_run.stdout_data)
    self.assertIn('Bug[normal]: NP_ALWAYS_NULL', pants_run.stdout_data)
    self.assertIn('Bug[low]: VA_FORMAT_STRING_USES_NEWLINE', pants_run.stdout_data)
    self.assertNotIn('Errors:', pants_run.stdout_data)
    self.assertIn('Bugs: 3 (High: 1, Normal: 1, Low: 1)', pants_run.stdout_data)
