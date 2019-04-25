# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.engine.fs import PathGlobs, Snapshot
from pants.source.filespec import matches_filespec
from pants_test.test_base import TestBase


class FilespecTest(TestBase):
  def assert_rule_match(self, glob, expected_matches, negate=False):
    """Tests that in-memory glob matching matches lazy-filesystem traversing globs."""
    if negate:
      assertMatch, match_state = self.assertFalse, 'erroneously matches'
    else:
      assertMatch, match_state = self.assertTrue, "doesn't match"

    # Confirm in-memory behaviour.
    for expected in expected_matches:
      assertMatch(
          matches_filespec(expected, {'globs': [glob]}),
          '{} {} path `{}`'.format(glob, match_state, expected),
      )

    # And confirm that it matches on-disk behaviour.
    for expected in expected_matches:
      if expected.endswith('/'):
        self.create_dir(expected)
      else:
        self.create_file(expected)
    snapshot, = self.scheduler.product_request(Snapshot, [PathGlobs([glob])])
    if negate:
      subset = set(expected_matches).intersection(set(snapshot.files))
      self.assertEquals(subset, set(), '{} {} path(s) {}'.format(glob, match_state, subset))
    else:
      self.assertEquals(sorted(expected_matches), sorted(snapshot.files))

  def test_matches_single_star_0(self):
    self.assert_rule_match('a/b/*/f.py', ('a/b/c/f.py', 'a/b/q/f.py'))

  def test_matches_single_star_0_neg(self):
    self.assert_rule_match('a/b/*/f.py', ('a/b/c/d/f.py','a/b/f.py'), negate=True)

  def test_matches_single_star_1(self):
    self.assert_rule_match('foo/bar/*', ('foo/bar/baz', 'foo/bar/bar'))

  def test_matches_single_star_2(self):
    self.assert_rule_match('*/bar/b*', ('foo/bar/baz', 'foo/bar/bar'))

  def test_matches_single_star_2_neg(self):
    self.assert_rule_match('*/bar/b*', ('foo/koo/bar/baz', 'foo/bar/bar/zoo'), negate=True)

  def test_matches_single_star_3(self):
    self.assert_rule_match('*/[be]*/b*', ('foo/bar/baz', 'foo/bar/bar'))

  def test_matches_single_star_4(self):
    self.assert_rule_match('foo*/bar', ('foofighters/bar', 'foofighters.venv/bar'))

  def test_matches_single_star_4_neg(self):
    self.assert_rule_match('foo*/bar', ('foofighters/baz/bar',), negate=True)

  def test_matches_double_star_0(self):
    self.assert_rule_match('**', ('a/b/c', 'b'))

  def test_matches_double_star_1(self):
    self.assert_rule_match('a/**/f', ('a/f', 'a/b/c/d/e/f'))

  def test_matches_double_star_2(self):
    self.assert_rule_match('a/b/**', ('a/b/d', 'a/b/c/d/e/f'))

  def test_matches_double_star_2_neg(self):
    self.assert_rule_match('a/b/**', ('a/b',), negate=True)

  def test_matches_dots(self):
    self.assert_rule_match('.*', ('.dots', '.dips'))

  def test_matches_dots_relative(self):
    self.assert_rule_match('./*.py', ('f.py', 'g.py'))

  def test_matches_dots_neg(self):
    self.assert_rule_match(
      '.*',
      ('b', 'a/non/dot/dir/file.py', 'dist', 'all/nested/.dot', '.some/hidden/nested/dir/file.py'),
      negate=True
    )

  def test_matches_dirs(self):
    self.assert_rule_match('dist/', ('dist',))

  def test_matches_dirs_neg(self):
    self.assert_rule_match('dist/', ('not_dist', 'cdist', 'dist.py', 'dist/dist'), negate=True)

  def test_matches_dirs_dots(self):
    self.assert_rule_match(
      'build-support/*.venv/',
      ('build-support/blah.venv',
       'build-support/rbt.venv')
    )

  def test_matches_dirs_dots_neg(self):
    self.assert_rule_match('build-support/*.venv/',
                           ('build-support/rbt.venv.but_actually_a_file',),
                           negate=True)

  def test_matches_literals(self):
    self.assert_rule_match('a', ('a',))

  def test_matches_literal_dir(self):
    self.assert_rule_match('a/b/c', ('a/b/c',))

  def test_matches_literal_file(self):
    self.assert_rule_match('a/b/c.py', ('a/b/c.py',))
