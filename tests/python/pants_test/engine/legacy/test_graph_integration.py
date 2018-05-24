# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.build_graph.address_lookup_error import AddressLookupError
from pants.option.errors import ParseError
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

    pants_run = self.run_pants(['list', target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'warn',
      },
    })
    self.assert_success(pants_run)

    for as_zsh_glob in expected_globs:
      warning_msg = self._ERR_FMT.format(
        base=self._SOURCES_TARGET_BASE,
        name=target_name,
        desc='sources',
        glob=glob_str,
        as_zsh_glob=as_zsh_glob)
      self.assertIn(warning_msg, pants_run.stderr_data)

  @unittest.skip('Skipped to expedite landing #5769: see #5863')
  def test_missing_sources_warnings(self):
    for target_name in self._SOURCES_ERR_MSGS.keys():
      self._list_target_check_warnings(target_name)

  @unittest.skip('Skipped to expedite landing #5769: see #5863')
  def test_existing_sources(self):
    target_full = '{}:text'.format(self._SOURCES_TARGET_BASE)
    pants_run = self.run_pants(['list', target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'warn',
      },
    })
    self.assert_success(pants_run)
    self.assertNotIn("WARN]", pants_run.stderr_data)

  @unittest.skip('Skipped to expedite landing #5769: see #5863')
  def test_missing_bundles_warnings(self):
    target_full = '{}:{}'.format(self._BUNDLE_TARGET_BASE, self._BUNDLE_TARGET_NAME)
    pants_run = self.run_pants(['list', target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'warn',
      },
    })

    self.assert_success(pants_run)

    # FIXME: this fails because we just report the string arguments passed to rglobs(), not the
    # zsh-style globs that they expand to (as we did in the previous iteration of this). We should
    # provide both the specific argument that failed, as well as the glob it expanded to for
    # clarity.
    for glob_str, expected_globs in self._BUNDLE_ERR_MSGS:
      for as_zsh_glob in expected_globs:
        warning_msg = self._ERR_FMT.format(
          base=self._BUNDLE_TARGET_BASE,
          name=self._BUNDLE_TARGET_NAME,
          desc='fileset',
          glob=glob_str,
          as_zsh_glob=as_zsh_glob)
        self.assertIn(warning_msg, pants_run.stderr_data)

  @unittest.skip('Skipped to expedite landing #5769: see #5863')
  def test_existing_bundles(self):
    target_full = '{}:mapper'.format(self._BUNDLE_TARGET_BASE)
    pants_run = self.run_pants(['list', target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'warn',
      },
    })
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
    self.assertIn(AddressLookupError.__name__, pants_run.stderr_data)
    expected_msg = """
Exception message: Build graph construction failed: ExecutionError Received unexpected Throw state(s):
Computing Select(Specs(dependencies=(SingleAddress(directory=u\'testprojects/src/python/sources\', name=u\'some-missing-some-not\'),)), =TransitiveHydratedTargets)
  Computing Task(transitive_hydrated_targets, Specs(dependencies=(SingleAddress(directory=u\'testprojects/src/python/sources\', name=u\'some-missing-some-not\'),)), =TransitiveHydratedTargets)
    Computing Task(transitive_hydrated_target, testprojects/src/python/sources:some-missing-some-not, =TransitiveHydratedTarget)
      Computing Task(hydrate_target, testprojects/src/python/sources:some-missing-some-not, =HydratedTarget)
        Computing Task(hydrate_sources, SourcesField(address=BuildFileAddress(testprojects/src/python/sources/BUILD, some-missing-some-not), arg=sources, filespecs={u\'exclude\': [], u\'globs\': [u\'*.txt\', u\'*.rs\']}), =HydratedField)
          Computing Snapshot(Key(val="PathGlobs(include=(u\\\'testprojects/src/python/sources/*.txt\\\', u\\\'testprojects/src/python/sources/*.rs\\\'), exclude=(), glob_match_error_behavior=\\\'error\\\')"))
            Throw(PathGlobs expansion failed: Throw(Globs did not match. Excludes were: []. Unmatched globs were: ["testprojects/src/python/sources/*.rs"]., "<pants native internals>"))
              Traceback (no traceback):
                <pants native internals>
              Exception: PathGlobs expansion failed: Throw(Globs did not match. Excludes were: []. Unmatched globs were: ["testprojects/src/python/sources/*.rs"]., "<pants native internals>")
"""
    self.assertIn(expected_msg, pants_run.stderr_data)

    bundle_target_full = '{}:{}'.format(self._BUNDLE_TARGET_BASE, self._BUNDLE_TARGET_NAME)

    pants_run = self.run_pants(['list', bundle_target_full], config={
      GLOBAL_SCOPE_CONFIG_SECTION: {
        'glob_expansion_failure': 'error',
      },
    })
    self.assert_failure(pants_run)
    self.assertIn(AddressLookupError.__name__, pants_run.stderr_data)
    # TODO: this is passing, but glob_match_error_behavior='ignore' in the target. We should have a
    # field which targets with bundles (and/or sources) can override which is the same as the global
    # option.
    expected_msg = """
Exception message: Build graph construction failed: ExecutionError Received unexpected Throw state(s):
Computing Select(Specs(dependencies=(SingleAddress(directory=u\'testprojects/src/java/org/pantsbuild/testproject/bundle\', name=u\'missing-bundle-fileset\'),)), =TransitiveHydratedTargets)
  Computing Task(transitive_hydrated_targets, Specs(dependencies=(SingleAddress(directory=u\'testprojects/src/java/org/pantsbuild/testproject/bundle\', name=u\'missing-bundle-fileset\'),)), =TransitiveHydratedTargets)
    Computing Task(transitive_hydrated_target, testprojects/src/java/org/pantsbuild/testproject/bundle:missing-bundle-fileset, =TransitiveHydratedTarget)
      Computing Task(hydrate_target, testprojects/src/java/org/pantsbuild/testproject/bundle:missing-bundle-fileset, =HydratedTarget)
        Computing Task(hydrate_bundles, BundlesField(address=BuildFileAddress(testprojects/src/java/org/pantsbuild/testproject/bundle/BUILD, missing-bundle-fileset), bundles=[BundleAdaptor(fileset=[\'a/b/file1.txt\']), BundleAdaptor(fileset=RGlobs(\'*.aaaa\', \'*.bbbb\')), BundleAdaptor(fileset=Globs(\'*.aaaa\')), BundleAdaptor(fileset=ZGlobs(\'**/*.abab\')), BundleAdaptor(fileset=[\'file1.aaaa\', \'file2.aaaa\'])], filespecs_list=[{u\'exclude\': [], u\'globs\': [u\'a/b/file1.txt\']}, {u\'exclude\': [], u\'globs\': [u\'**/*.aaaa\', u\'**/*.bbbb\']}, {u\'exclude\': [], u\'globs\': [u\'*.aaaa\']}, {u\'exclude\': [], u\'globs\': [u\'**/*.abab\']}, {u\'exclude\': [], u\'globs\': [u\'file1.aaaa\', u\'file2.aaaa\']}], path_globs_list=[PathGlobs(include=(u\'testprojects/src/java/org/pantsbuild/testproject/bundle/a/b/file1.txt\',), exclude=(), glob_match_error_behavior=\'ignore\'), PathGlobs(include=(u\'testprojects/src/java/org/pantsbuild/testproject/bundle/**/*.aaaa\', u\'testprojects/src/java/org/pantsbuild/testproject/bundle/**/*.bbbb\'), exclude=(), glob_match_error_behavior=\'ignore\'), PathGlobs(include=(u\'testprojects/src/java/org/pantsbuild/testproject/bundle/*.aaaa\',), exclude=(), glob_match_error_behavior=\'ignore\'), PathGlobs(include=(u\'testprojects/src/java/org/pantsbuild/testproject/bundle/**/*.abab\',), exclude=(), glob_match_error_behavior=\'ignore\'), PathGlobs(include=(u\'testprojects/src/java/org/pantsbuild/testproject/bundle/file1.aaaa\', u\'testprojects/src/java/org/pantsbuild/testproject/bundle/file2.aaaa\'), exclude=(), glob_match_error_behavior=\'ignore\')]), =HydratedField)
          Computing Snapshot(Key(val="PathGlobs(include=(u\\\'testprojects/src/java/org/pantsbuild/testproject/bundle/*.aaaa\\\',), exclude=(), glob_match_error_behavior=\\\'error\\\')"))
            Throw(PathGlobs expansion failed: Throw(Globs did not match. Excludes were: []. Unmatched globs were: ["testprojects/src/java/org/pantsbuild/testproject/bundle/*.aaaa"]., "<pants native internals>"))
              Traceback (no traceback):
                <pants native internals>
              Exception: PathGlobs expansion failed: Throw(Globs did not match. Excludes were: []. Unmatched globs were: ["testprojects/src/java/org/pantsbuild/testproject/bundle/*.aaaa"]., "<pants native internals>")
"""
    self.assertIn(expected_msg, pants_run.stderr_data)

  def test_exception_invalid_option_value(self):
    # NB: 'allow' is not a valid value for --glob-expansion-failure.
    pants_run = self.run_pants(['--glob-expansion-failure=allow'])
    self.assert_failure(pants_run)
    self.assertIn(ParseError.__name__, pants_run.stderr_data)
    expected_msg = (
      "`allow` is not an allowed value for option glob_expansion_failure in global scope. "
      "Must be one of: [u'ignore', u'warn', u'error']")
    self.assertIn(expected_msg, pants_run.stderr_data)
