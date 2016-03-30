# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil
import tempfile
import unittest

from pants.reporting.linkify import linkify


def ensure_dir_exists(path):
  os.makedirs(path)


def ensure_file_exists(path):
  ensure_dir_exists(os.path.dirname(path))
  open(path, 'a').close()


class LinkifyTest(unittest.TestCase):
  def setUp(self):
    self._buildroot = tempfile.mkdtemp(prefix='test_html_reporter')

  def tearDown(self):
    if os.path.exists(self._buildroot):
      shutil.rmtree(self._buildroot, ignore_errors=True)

  def _do_test_linkify(self, expected_link, url, memo=None):
    memo = {} if memo is None else memo
    s = 'foo {} bar'.format(url)
    expected = 'foo <a target="_blank" href="{}">{}</a> bar'.format(expected_link, url)
    linkified = linkify(self._buildroot, s, memo)
    self.assertEqual(expected, linkified)

  def _do_test_not_linkified(self, url, memo=None):
    memo = {} if memo is None else memo
    s = 'foo {} bar'.format(url)
    linkified = linkify(self._buildroot, s, memo)
    self.assertEqual(s, linkified)

  def test_linkify_absolute_paths(self):
    relpath = 'underscore_and.dot/and-dash/baz'
    path = os.path.join(self._buildroot, relpath)
    ensure_file_exists(path)
    self._do_test_linkify('/browse/{}'.format(relpath), path)

  def test_linkify_relative_paths(self):
    relpath = 'underscore_and.dot/and-dash/baz'
    path = os.path.join(self._buildroot, relpath)
    ensure_file_exists(path)
    self._do_test_linkify('/browse/{}'.format(relpath), relpath)

  def test_linkify_relative_path_outside_buildroot(self):
    self._do_test_not_linkified('../definitely/outside/baz')

  def test_linkify_non_existent_relative_paths(self):
    relpath = 'underscore_and.dot/and-dash/baz'

    self._do_test_not_linkified(relpath)

  def test_linkify_http(self):
    url = 'http://foobar.com/baz/qux'
    self._do_test_linkify(url, url)

    url = 'http://localhost:666/baz/qux'
    self._do_test_linkify(url, url)

  def test_linkify_https(self):
    url = 'https://foobar.com/baz/qux'
    self._do_test_linkify(url, url)

  def test_linkify_sftp(self):
    url = 'sftp://foobar.com/baz/qux'
    self._do_test_not_linkified(url)

  def test_linkify_target(self):
    ensure_file_exists(os.path.join(self._buildroot, 'foo/bar/BUILD'))
    self._do_test_linkify('/browse/foo/bar/BUILD', 'foo/bar')
    self._do_test_linkify('/browse/foo/bar/BUILD', 'foo/bar:target')

  def test_linkify_suffix(self):
    ensure_file_exists(os.path.join(self._buildroot, 'foo/bar/BUILD.suffix'))
    self._do_test_linkify('/browse/foo/bar/BUILD.suffix', 'foo/bar')

  def test_linkify_stores_values_in_memo(self):
    url = 'https://foobar.com/baz/qux'
    memo = {}
    self._do_test_linkify(url, url, memo)
    self.assertEqual(url, memo[url])

  # Technically, if there's a file named ....., we should linkify it.
  # This is thus not actually verifying desired behavior. However,
  # this seems the most reasonable way to verify that linkify does
  # not go crazy on dots, as described in linkify.py.
  def test_linkify_ignore_many_dots(self):
    url = '.....'
    self._do_test_not_linkified(url)
