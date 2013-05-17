import os
import shutil
import tempfile
import unittest

from twitter.pants.reporting.linkify import linkify


def ensure_file_exists(path):
  os.makedirs(os.path.dirname(path))
  open(path, 'a').close()

class RunInfoTest(unittest.TestCase):
  def setUp(self):
    self._buildroot = tempfile.mkdtemp(prefix='test_html_reporter')

  def tearDown(self):
    if os.path.exists(self._buildroot):
      shutil.rmtree(self._buildroot, ignore_errors=True)

  def _do_test_linkify(self, expected, s):
    linkified = linkify(self._buildroot, s)
    self.assertEqual(expected, linkified)

  def test_linkify_absolute_paths(self):
    relpath = 'underscore_and.dot/and-dash/baz'
    path = os.path.join(self._buildroot, relpath)
    ensure_file_exists(path)
    self._do_test_linkify(
      'foo <a target="_blank" href="/browse/%s">%s</a> bar' % (relpath, path),
      'foo %s bar' % path)

  def test_linkify_relative_paths(self):
    relpath = 'underscore_and.dot/and-dash/baz'
    path = os.path.join(self._buildroot, relpath)
    ensure_file_exists(path)
    self._do_test_linkify(
      'foo <a target="_blank" href="/browse/%s">%s</a> bar' % (relpath, relpath),
      'foo %s bar' % relpath)

  def test_linkify_http(self):
    url = 'http://foobar.com/baz/qux'
    self._do_test_linkify(
      'foo <a target="_blank" href="%s">%s</a> bar' % (url, url),
      'foo %s bar' % url)

  def test_linkify_https(self):
    url = 'https://foobar.com/baz/qux'
    self._do_test_linkify('foo <a target="_blank" href="%s">%s</a> bar' % (url, url),
                          'foo %s bar' % url)

  def test_linkify_target(self):
    ensure_file_exists(os.path.join(self._buildroot, 'foo/bar/BUILD'))
    self._do_test_linkify(
      '<a target="_blank" href="/browse/foo/bar/BUILD">foo/bar:target</a>',
      'foo/bar:target')
    self._do_test_linkify(
      '<a target="_blank" href="/browse/foo/bar/BUILD">foo/bar</a>',
      'foo/bar')
