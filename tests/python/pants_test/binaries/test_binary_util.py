# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

import mock

from pants.binaries.binary_util import BinaryUtil
from pants.net.http.fetcher import Fetcher
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open
from pants_test.base_test import BaseTest


class BinaryUtilTest(BaseTest):
  """Tests binary_util's pants_support_baseurls handling."""

  class MapFetcher(object):
    """Class which pretends to be a pants.net.http.Fetcher, but is actually a dictionary."""

    def __init__(self, read_map):
      self._map = read_map

    def download(self, url, path_or_fd=None, **kwargs):
      if not url in self._map:
        raise IOError("404: Virtual URL '{}' does not exist.".format(url))
      if not path_or_fd:
        raise AssertionError("Expected path_or_fd to be set")
      path_or_fd.write(self._map[url])
      return path_or_fd

    def keys(self):
      return self._map.keys()

    def values(self):
      return self._map.values()

    def __getitem__(self, key):
      return self._map[key]  # Vanilla internal map access (without lambda shenanigans).

  @classmethod
  def _fake_base(cls, name):
    return 'fake-url-{name}'.format(name=name)

  @classmethod
  def _fake_url(cls, binaries, base, binary_key):
    binary_util = BinaryUtil([], 0, '/tmp')
    supportdir, version, name = binaries[binary_key]
    binary = binary_util._select_binary_base_path(supportdir, version, binary_key)
    return '{base}/{binary}'.format(base=base, binary=binary)

  def test_timeout(self):
    fetcher = mock.create_autospec(Fetcher, spec_set=True)
    binary_util = BinaryUtil(baseurls=['http://binaries.example.com'],
                             timeout_secs=42,
                             bootstrapdir='/tmp')
    self.assertFalse(fetcher.download.called)

    with binary_util._select_binary_stream('a-binary', 'a-binary/v1.2/a-binary', fetcher=fetcher):
      fetcher.download.assert_called_once_with('http://binaries.example.com/a-binary/v1.2/a-binary',
                                               listener=mock.ANY,
                                               path_or_fd=mock.ANY,
                                               timeout_secs=42)

  def test_nobases(self):
    """Tests exception handling if build support urls are improperly specified."""
    binary_util = BinaryUtil(baseurls=[], timeout_secs=30, bootstrapdir='/tmp')
    with self.assertRaises(binary_util.NoBaseUrlsError):
      binary_path = binary_util._select_binary_base_path(supportdir='bin/protobuf',
                                                         version='2.4.1',
                                                         name='protoc')
      with binary_util._select_binary_stream(name='protoc', binary_path=binary_path):
        self.fail('Expected acquisition of the stream to raise.')

  def test_support_url_multi(self):
    """Tests to make sure existing base urls function as expected."""

    with temporary_dir() as invalid_local_files, temporary_dir() as valid_local_files:
      binary_util = BinaryUtil(
        baseurls=[
          'BLATANTLY INVALID URL',
          'https://dl.bintray.com/pantsbuild/bin/reasonably-invalid-url',
          invalid_local_files,
          valid_local_files,
          'https://dl.bintray.com/pantsbuild/bin/another-invalid-url',
        ],
        timeout_secs=30,
        bootstrapdir='/tmp')

      binary_path = binary_util._select_binary_base_path(supportdir='bin/protobuf',
                                                         version='2.4.1',
                                                         name='protoc')
      contents = b'proof'
      with safe_open(os.path.join(valid_local_files, binary_path), 'wb') as fp:
        fp.write(contents)

      with binary_util._select_binary_stream(name='protoc', binary_path=binary_path) as stream:
        self.assertEqual(contents, stream())

  def test_support_url_fallback(self):
    """Tests fallback behavior with multiple support baseurls.

    Mocks up some dummy baseurls and then swaps out the URL reader to make sure urls are accessed
    and others are not.
    """
    fake_base, fake_url = self._fake_base, self._fake_url
    bases = [fake_base('apple'), fake_base('orange'), fake_base('banana')]
    binary_util = BinaryUtil(bases, 30, '/tmp')

    binaries = {t[2]: t for t in (('bin/protobuf', '2.4.1', 'protoc'),
                                  ('bin/ivy', '4.3.7', 'ivy'),
                                  ('bin/bash', '4.4.3', 'bash'))}
    fetcher = self.MapFetcher({
      fake_url(binaries, bases[0], 'protoc'): 'SEEN PROTOC',
      fake_url(binaries, bases[0], 'ivy'): 'SEEN IVY',
      fake_url(binaries, bases[1], 'bash'): 'SEEN BASH',
      fake_url(binaries, bases[1], 'protoc'): 'UNSEEN PROTOC 1',
      fake_url(binaries, bases[2], 'protoc'): 'UNSEEN PROTOC 2',
      fake_url(binaries, bases[2], 'ivy'): 'UNSEEN IVY 2',
    })

    unseen = [item for item in fetcher.values() if item.startswith('SEEN ')]
    for supportdir, version, name in binaries.values():
      binary_path = binary_util._select_binary_base_path(supportdir=supportdir,
                                                         version=version,
                                                         name=name)
      with binary_util._select_binary_stream(name=name,
                                             binary_path=binary_path,
                                             fetcher=fetcher) as stream:
        result = stream()
        self.assertEqual(result, 'SEEN ' + name.upper())
        unseen.remove(result)
    self.assertEqual(0, len(unseen))  # Make sure we've seen all the SEENs.

  def test_select_binary_base_path_linux(self):
    binary_util = BinaryUtil([], 0, '/tmp')

    def uname_func():
      return "linux", "dontcare1", "dontcare2", "dontcare3", "amd64"

    self.assertEquals("supportdir/linux/x86_64/name/version",
                      binary_util._select_binary_base_path("supportdir", "name", "version",
                                                           uname_func=uname_func))

  def test_select_binary_base_path_darwin(self):
    binary_util = BinaryUtil([], 0, '/tmp')

    def uname_func():
      return "darwin", "dontcare1", "14.9", "dontcare2", "dontcare3",

    self.assertEquals("supportdir/mac/10.10/name/version",
                      binary_util._select_binary_base_path("supportdir", "name", "version",
                                                           uname_func=uname_func))

  def test_select_binary_base_path_missing_os(self):
    binary_util = BinaryUtil([], 0, '/tmp')

    def uname_func():
      return "vms", "dontcare1", "999.9", "dontcare2", "VAX9"

    with self.assertRaisesRegexp(BinaryUtil.MissingMachineInfo,
                                 r'Pants has no binaries for vms'):
      binary_util._select_binary_base_path("supportdir", "name", "version", uname_func=uname_func)

  def test_select_binary_base_path_missing_version(self):
    binary_util = BinaryUtil([], 0, '/tmp')

    def uname_func():
      return "darwin", "dontcare1", "999.9", "dontcare2", "x86_64"

    os_id = ('darwin', '999')
    with self.assertRaisesRegexp(BinaryUtil.MissingMachineInfo,
                                 r'Update --binaries-path-by-id to find binaries for '
                                 r'{}'.format(re.escape(repr(os_id)))):
      binary_util._select_binary_base_path("supportdir", "name", "version", uname_func=uname_func)

  def test_select_binary_base_path_override(self):
    binary_util = BinaryUtil([], 0, '/tmp',
                             {('darwin', '100'): ['skynet', '42']})

    def uname_func():
      return "darwin", "dontcare1", "100.99", "dontcare2", "t1000"

    self.assertEquals("supportdir/skynet/42/name/version",
                      binary_util._select_binary_base_path("supportdir", "name", "version",
                                                           uname_func=uname_func))
