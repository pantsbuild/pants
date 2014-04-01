# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import shutil
import tempfile
import unittest

from pants.reporting.linkify import linkify


def ensure_file_exists(path):
  os.makedirs(os.path.dirname(path))
  open(path, 'a').close()

class RunInfoTest(unittest.TestCase):
  def setUp(self):
    self._buildroot = tempfile.mkdtemp(prefix='test_html_reporter')

  def tearDown(self):
    if os.path.exists(self._buildroot):
      shutil.rmtree(self._buildroot, ignore_errors=True)

  def _do_test_linkify(self, expected_link, url):
    s = 'foo %s bar' % url
    expected = 'foo <a target="_blank" href="%s">%s</a> bar' % (expected_link, url)
    linkified = linkify(self._buildroot, s)
    self.assertEqual(expected, linkified)

  def test_linkify_absolute_paths(self):
    relpath = 'underscore_and.dot/and-dash/baz'
    path = os.path.join(self._buildroot, relpath)
    ensure_file_exists(path)
    self._do_test_linkify('/browse/%s' % relpath, path)

  def test_linkify_relative_paths(self):
    relpath = 'underscore_and.dot/and-dash/baz'
    path = os.path.join(self._buildroot, relpath)
    ensure_file_exists(path)
    self._do_test_linkify('/browse/%s' % relpath, relpath)

  def test_linkify_http(self):
    url = 'http://foobar.com/baz/qux'
    self._do_test_linkify(url, url)

    url = 'http://localhost:666/baz/qux'
    self._do_test_linkify(url, url)

  def test_linkify_https(self):
    url = 'https://foobar.com/baz/qux'
    self._do_test_linkify(url, url)

  def test_linkify_target(self):
    ensure_file_exists(os.path.join(self._buildroot, 'foo/bar/BUILD'))
    self._do_test_linkify('/browse/foo/bar/BUILD', 'foo/bar')
    self._do_test_linkify('/browse/foo/bar/BUILD', 'foo/bar:target')
