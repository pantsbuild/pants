# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import re
import unittest

from pants.source.filespec import glob_to_regex


class GlobToRegexTest(unittest.TestCase):
  def assert_rule_match(self, glob, expected_matches, negate=False):
    if negate:
      asserter, match_state = self.assertIsNone, 'erroneously matches'
    else:
      asserter, match_state = self.assertIsNotNone, "doesn't match"

    regex = glob_to_regex(glob)
    for expected in expected_matches:
      asserter(re.match(regex, expected), 'glob_to_regex(`{}`) -> `{}` {} path `{}`'
                                          .format(glob, regex, match_state, expected))

  def test_glob_to_regex_single_star_0(self):
    self.assert_rule_match('a/b/*/f.py', ('a/b/c/f.py', 'a/b/q/f.py'))

  def test_glob_to_regex_single_star_0_neg(self):
    self.assert_rule_match('a/b/*/f.py', ('a/b/c/d/f.py','a/b/f.py'), negate=True)

  def test_glob_to_regex_single_star_1(self):
    self.assert_rule_match('foo/bar/*', ('foo/bar/baz', 'foo/bar/bar'))

  def test_glob_to_regex_single_star_2(self):
    self.assert_rule_match('*/bar/b*', ('foo/bar/baz', 'foo/bar/bar'))

  def test_glob_to_regex_single_star_2_neg(self):
    self.assert_rule_match('*/bar/b*', ('foo/koo/bar/baz', 'foo/bar/bar/zoo'), negate=True)

  def test_glob_to_regex_single_star_3(self):
    self.assert_rule_match('/*/[be]*/b*', ('/foo/bar/baz', '/foo/bar/bar'))

  def test_glob_to_regex_single_star_4(self):
    self.assert_rule_match('/foo*/bar', ('/foofighters/bar', '/foofighters.venv/bar'))

  def test_glob_to_regex_single_star_4_neg(self):
    self.assert_rule_match('/foo*/bar', ('/foofighters/baz/bar',), negate=True)

  def test_glob_to_regex_double_star_0(self):
    self.assert_rule_match('**', ('a/b/c', 'a'))

  def test_glob_to_regex_double_star_1(self):
    self.assert_rule_match('a/**/f', ('a/f', 'a/b/c/d/e/f'))

  def test_glob_to_regex_double_star_2(self):
    self.assert_rule_match('a/b/**', ('a/b/c', 'a/b/c/d/e/f'))

  def test_glob_to_regex_double_star_2_neg(self):
    self.assert_rule_match('a/b/**', ('a/b'), negate=True)

  def test_glob_to_regex_leading_slash_0(self):
    self.assert_rule_match('/a/*', ('/a/a', '/a/b.py'))

  def test_glob_to_regex_leading_slash_0_neg(self):
    self.assert_rule_match('/a/*', ('a/a', 'a/b.py'), negate=True)

  def test_glob_to_regex_leading_slash_1(self):
    self.assert_rule_match('/*', ('/a', '/a.py'))

  def test_glob_to_regex_leading_slash_1_neg(self):
    self.assert_rule_match('/*', ('a', 'a.py'), negate=True)

  def test_glob_to_regex_leading_slash_2(self):
    self.assert_rule_match('/**', ('/a', '/a/b/c/d/e/f'))

  def test_glob_to_regex_leading_slash_2_neg(self):
    self.assert_rule_match('/**', ('a', 'a/b/c/d/e/f'), negate=True)

  def test_glob_to_regex_dots(self):
    self.assert_rule_match('.*', ('.pants.d', '.', '..', '.pids'))

  def test_glob_to_regex_dots_neg(self):
    self.assert_rule_match(
      '.*',
      ('a', 'a/non/dot/dir/file.py', 'dist', 'all/nested/.dot', '.some/hidden/nested/dir/file.py'),
      negate=True
    )

  def test_glob_to_regex_dirs(self):
    self.assert_rule_match('dist/', ('dist',))

  def test_glob_to_regex_dirs_neg(self):
    self.assert_rule_match('dist/', ('not_dist', 'cdist', 'dist.py', 'dist/dist'), negate=True)

  def test_glob_to_regex_dirs_dots(self):
    self.assert_rule_match(
      'build-support/*.venv/',
      ('build-support/*.venv',
       'build-support/rbt.venv')
    )

  def test_glob_to_regex_dirs_dots_neg(self):
    self.assert_rule_match('build-support/*.venv/',
                           ('build-support/rbt.venv.but_actually_a_file',),
                           negate=True)

  def test_glob_to_regex_literals(self):
    self.assert_rule_match('a', ('a',))

  def test_glob_to_regex_literal_dir(self):
    self.assert_rule_match('a/b/c', ('a/b/c',))

  def test_glob_to_regex_literal_file(self):
    self.assert_rule_match('a/b/c.py', ('a/b/c.py',))
