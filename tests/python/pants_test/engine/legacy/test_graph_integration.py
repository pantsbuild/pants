# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.build_graph.address_lookup_error import AddressLookupError
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
  }

  _WARN_FMT = """WARN] Globs did not match. Excludes were: {excludes}. Unmatched globs were: {unmatched}.\n\n"""

  _BUNDLE_ERR_MSGS = [
    ['*.aaaa'],
    ['**/*.aaaa', '**/*.bbbb'],
    ['**/*.abab'],
    ['file1.aaaa', 'file2.aaaa'],
  ]

  _BUNDLE_TARGET_BASE = 'testprojects/src/java/org/pantsbuild/testproject/bundle'

  def _list_target_check_warnings_sources(self, target_name):
    target_full = '{}:{}'.format(self._SOURCES_TARGET_BASE, target_name)
    glob_str, expected_globs = self._SOURCES_ERR_MSGS[target_name]

    pants_run = self.run_pants(['list', target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'warn',
      },
    })
    self.assert_success(pants_run)

    warning_msg = (
      "WARN] Globs did not match. Excludes were: " +
      '[]' +
      ". Unmatched globs were: " +
      "[{}]".format(', '.join('"{}"'.format(os.path.join(self._SOURCES_TARGET_BASE, g)) for g in expected_globs)) +
      ".\n\n")
    self.assertEqual(warning_msg, pants_run.stderr_data)

  _ERR_TARGETS = {
    'testprojects/src/python/sources:some-missing-some-not': [
      "globs('*.txt', '*.rs')",
      "Snapshot(PathGlobs(include=(u\'testprojects/src/python/sources/*.txt\', u\'testprojects/src/python/sources/*.rs\'), exclude=(), glob_match_error_behavior<=GlobMatchErrorBehavior>=GlobMatchErrorBehavior(failure_behavior=error), conjunction<=GlobExpansionConjunction>=GlobExpansionConjunction(conjunction=all_match)))",
      "Globs did not match. Excludes were: []. Unmatched globs were: [\"testprojects/src/python/sources/*.rs\"].",
    ],
    'testprojects/src/python/sources:missing-sources': [
      "*.scala",
      "Snapshot(PathGlobs(include=(u\'testprojects/src/python/sources/*.scala\',), exclude=(u\'testprojects/src/python/sources/*Test.scala\', u\'testprojects/src/python/sources/*Spec.scala\'), glob_match_error_behavior<=GlobMatchErrorBehavior>=GlobMatchErrorBehavior(failure_behavior=error), conjunction<=GlobExpansionConjunction>=GlobExpansionConjunction(conjunction=any_match)))",
      "Globs did not match. Excludes were: [\"testprojects/src/python/sources/*Test.scala\", \"testprojects/src/python/sources/*Spec.scala\"]. Unmatched globs were: [\"testprojects/src/python/sources/*.scala\"].",
    ],
    'testprojects/src/java/org/pantsbuild/testproject/bundle:missing-bundle-fileset': [
      "['a/b/file1.txt']",
      "RGlobs('*.aaaa', '*.bbbb')",
      "Globs('*.aaaa')",
      "ZGlobs('**/*.abab')",
      "['file1.aaaa', 'file2.aaaa']",
      "Snapshot(PathGlobs(include=(u\'testprojects/src/java/org/pantsbuild/testproject/bundle/*.aaaa\',), exclude=(), glob_match_error_behavior<=GlobMatchErrorBehavior>=GlobMatchErrorBehavior(failure_behavior=error), conjunction<=GlobExpansionConjunction>=GlobExpansionConjunction(conjunction=all_match)))",
      "Globs did not match. Excludes were: []. Unmatched globs were: [\"testprojects/src/java/org/pantsbuild/testproject/bundle/*.aaaa\"].",
    ]
  }

  def _list_target_check_error(self, target_name):
    expected_excerpts = self._ERR_TARGETS[target_name]

    pants_run = self.run_pants(['list', target_name], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'error',
      },
    })
    self.assert_failure(pants_run)

    self.assertIn(AddressLookupError.__name__, pants_run.stderr_data)

    for excerpt in expected_excerpts:
      self.assertIn(excerpt, pants_run.stderr_data)

  def test_missing_sources_warnings(self):
    for target_name in self._SOURCES_ERR_MSGS.keys():
      self._list_target_check_warnings_sources(target_name)

  def test_existing_sources(self):
    target_full = '{}:text'.format(self._SOURCES_TARGET_BASE)
    pants_run = self.run_pants(['list', target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'warn',
      },
    })
    self.assert_success(pants_run)
    self.assertNotIn("WARN]", pants_run.stderr_data)

  def test_missing_bundles_warnings(self):
    target_full = '{}:missing-bundle-fileset'.format(self._BUNDLE_TARGET_BASE)
    pants_run = self.run_pants(['list', target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'warn',
      },
    })

    self.assert_success(pants_run)

    for msgs in self._BUNDLE_ERR_MSGS:
      warning_msg = (
        "WARN] Globs did not match. Excludes were: " +
        "[]" +
        ". Unmatched globs were: " +
        "[{}]".format(', '.join(('"' + os.path.join(self._BUNDLE_TARGET_BASE, m) + '"') for m in msgs)) +
        ".")
      self.assertIn(warning_msg, pants_run.stderr_data)

  def test_existing_bundles(self):
    target_full = '{}:mapper'.format(self._BUNDLE_TARGET_BASE)
    pants_run = self.run_pants(['list', target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'warn',
      },
    })
    self.assert_success(pants_run)
    self.assertNotIn("WARN]", pants_run.stderr_data)

  def test_error_message(self):
    for k in self._ERR_TARGETS:
      self._list_target_check_error(k)
