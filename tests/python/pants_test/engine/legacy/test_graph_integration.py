# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.option.scope import GLOBAL_SCOPE_CONFIG_SECTION
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GraphIntegrationTest(PantsRunIntegrationTest):

  _SOURCES_TARGET_BASE = 'testprojects/src/python/sources'

  _SOURCES_ERR_MSGS = {
    'missing-globs': ("globs('*.a')", ['*.a']),
    'missing-rglobs': ("rglobs('*.a')", ['**/*.a']),
    'missing-zglobs': ("zglobs('**/*.a')", ['**/*.a']),
    'missing-literal-files': (
      "['nonexistent_test_file.txt', 'another_nonexistent_file.txt']", [
      'nonexistent_test_file.txt',
      'another_nonexistent_file.txt',
    ]),
    'some-missing-some-not': ("globs('*.txt', '*.rs')", ['*.rs']),
    'overlapping-globs': ("globs('sources.txt', '*.txt')", ['*.txt']),
  }

  _BUNDLE_TARGET_BASE = 'testprojects/src/java/org/pantsbuild/testproject/bundle'
  _BUNDLE_TARGET_NAME = 'missing-bundle-fileset'

  _BUNDLE_ERR_MSGS = [
    ("rglobs('*.aaaa', '*.bbbb')", ['**/*.aaaa', '**/*.bbbb']),
    ("globs('*.aaaa')", ['*.aaaa']),
    ("zglobs('**/*.abab')", ['**/*.abab']),
    ("['file1.aaaa', 'file2.aaaa']", ['file1.aaaa', 'file2.aaaa']),
  ]

  _ERR_FMT = "WARN] In target {base}:{name} with {desc}={glob}: glob pattern '{as_zsh_glob}' did not match any files."

  def _list_target_check_warnings(self, target_name):
    target_full = '{}:{}'.format(self._SOURCES_TARGET_BASE, target_name)
    glob_str, expected_globs = self._SOURCES_ERR_MSGS[target_name]

    pants_run = self.run_pants(['list', target_full])
    self.assert_success(pants_run)

    for as_zsh_glob in expected_globs:
      warning_msg = self._ERR_FMT.format(
        base=self._SOURCES_TARGET_BASE,
        name=target_name,
        desc='sources',
        glob=glob_str,
        as_zsh_glob=as_zsh_glob)
      self.assertIn(warning_msg, pants_run.stderr_data)

  def test_missing_sources_warnings(self):
    for target_name in self._SOURCES_ERR_MSGS.keys():
      self._list_target_check_warnings(target_name)

  def test_existing_sources(self):
    target_full = '{}:text'.format(self._SOURCES_TARGET_BASE)
    pants_run = self.run_pants(['list', target_full])
    self.assert_success(pants_run)
    self.assertNotIn("WARN]", pants_run.stderr_data)

  def test_missing_bundles_warnings(self):
    target_full = '{}:{}'.format(self._BUNDLE_TARGET_BASE, self._BUNDLE_TARGET_NAME)
    pants_run = self.run_pants(['list', target_full])

    self.assert_success(pants_run)
    for glob_str, expected_globs in self._BUNDLE_ERR_MSGS:
      for as_zsh_glob in expected_globs:
        warning_msg = self._ERR_FMT.format(
          base=self._BUNDLE_TARGET_BASE,
          name=self._BUNDLE_TARGET_NAME,
          desc='fileset',
          glob=glob_str,
          as_zsh_glob=as_zsh_glob)
        self.assertIn(warning_msg, pants_run.stderr_data)

  def test_existing_bundles(self):
    target_full = '{}:mapper'.format(self._BUNDLE_TARGET_BASE)
    pants_run = self.run_pants(['list', target_full])
    self.assert_success(pants_run)
    self.assertNotIn("WARN]", pants_run.stderr_data)

  def test_exception_with_global_option(self):
    sources_target_full = '{}:some-missing-some-not'.format(self._SOURCES_TARGET_BASE)

    pants_run = self.run_pants(['list', sources_target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'error',
      },
    })
    self.assert_failure(pants_run)
    self.assertIn(
      """SourcesGlobMatchError: In target testprojects/src/python/sources:some-missing-some-not with sources=globs('*.txt', '*.rs'): Some globs failed to match and --glob-match-failure is set to GlobMatchErrorBehavior(failure_behavior<=str>=error). The failures were:
            glob pattern '*.rs' did not match any files.""", pants_run.stderr_data)

    bundle_target_full = '{}:{}'.format(self._BUNDLE_TARGET_BASE, self._BUNDLE_TARGET_NAME)

    pants_run = self.run_pants(['list', bundle_target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'error',
      },
    })
    self.assert_failure(pants_run)
    self.assertIn(
      """SourcesGlobMatchError: In target testprojects/src/java/org/pantsbuild/testproject/bundle:missing-bundle-fileset with fileset=rglobs('*.aaaa', '*.bbbb'): Some globs failed to match and --glob-match-failure is set to GlobMatchErrorBehavior(failure_behavior<=str>=error). The failures were:
            glob pattern '**/*.aaaa' did not match any files.
            glob pattern '**/*.bbbb' did not match any files.""", pants_run.stderr_data)

  def test_exception_invalid_option_value(self):
    # NB: 'allow' is not a valid value for --glob-expansion-failure.
    pants_run = self.run_pants(['list', '--glob-expansion-failure=allow'])
    self.assert_failure(pants_run)
    self.assertIn(
      "Exception message: Unrecognized command line flags on scope 'list': --glob-expansion-failure",
      pants_run.stderr_data)
