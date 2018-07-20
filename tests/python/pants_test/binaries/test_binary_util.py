# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
from builtins import object, str

import mock

from pants.binaries.binary_util import (BinaryRequest, BinaryToolFetcher, BinaryToolUrlGenerator,
                                        BinaryUtil)
from pants.net.http.fetcher import Fetcher
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_open
from pants_test.test_base import TestBase


logger = logging.getLogger(__name__)


class ExternalUrlGenerator(BinaryToolUrlGenerator):

  def generate_urls(self, version, host_platform):
    return ['https://example.com/some-binary', 'https://example.com/same-binary']

  # Make the __str__ deterministic, for testing exception messages.
  def __str__(self):
    return 'ExternalUrlGenerator(<example __str__()>)'


# TODO(cosmicexplorer): test requests with an archiver!
class BinaryUtilTest(TestBase):
  """Tests binary_util's binaries_baseurls handling."""

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
      return list(self._map.keys())

    def values(self):
      return list(self._map.values())

    def __getitem__(self, key):
      return self._map[key]  # Vanilla internal map access (without lambda shenanigans).

  @classmethod
  def _fake_base(cls, name):
    return 'fake-url-{name}'.format(name=name)

  @classmethod
  def _fake_url(cls, binaries, base, binary_key):
    binary_util = cls._gen_binary_util()
    supportdir, version, name = binaries[binary_key]
    binary_request = binary_util._make_deprecated_binary_request(supportdir, version, name)

    binary_path = binary_request.get_download_path(binary_util._host_platform())
    return '{base}/{binary}'.format(base=base, binary=binary_path)

  @classmethod
  def _gen_binary_tool_fetcher(cls, bootstrap_dir='/tmp', timeout_secs=30, fetcher=None,
                               ignore_cached_download=True):
    return BinaryToolFetcher(
      bootstrap_dir=bootstrap_dir,
      timeout_secs=timeout_secs,
      fetcher=fetcher,
      ignore_cached_download=ignore_cached_download)

  @classmethod
  def _gen_binary_util(cls, baseurls=[], path_by_id=None, allow_external_binary_tool_downloads=True,
                       uname_func=None, **kwargs):
    return BinaryUtil(
      baseurls=baseurls,
      binary_tool_fetcher=cls._gen_binary_tool_fetcher(**kwargs),
      path_by_id=path_by_id,
      allow_external_binary_tool_downloads=allow_external_binary_tool_downloads,
      uname_func=uname_func)

  @classmethod
  def _read_file(cls, file_path):
    with open(file_path, 'rb') as result_file:
      return result_file.read()

  def test_timeout(self):
    fetcher = mock.create_autospec(Fetcher, spec_set=True)
    timeout_value = 42
    binary_util = self._gen_binary_util(baseurls=['http://binaries.example.com'],
                                        timeout_secs=timeout_value,
                                        fetcher=fetcher)
    self.assertFalse(fetcher.download.called)

    fetch_path = binary_util.select_script(supportdir='a-binary', version='v1.2', name='a-binary')
    logger.debug("fetch_path: {}".format(fetch_path))
    fetcher.download.assert_called_once_with('http://binaries.example.com/a-binary/v1.2/a-binary',
                                             listener=mock.ANY,
                                             path_or_fd=mock.ANY,
                                             timeout_secs=timeout_value)

  def test_no_base_urls_error(self):
    """Tests exception handling if build support urls are improperly specified."""
    binary_util = self._gen_binary_util()

    with self.assertRaises(BinaryUtil.BinaryResolutionError) as cm:
      binary_util.select_script("supportdir", "version", "name")
    the_raised_exception_message = str(cm.exception)

    self.assertIn(BinaryUtil.NoBaseUrlsError.__name__, the_raised_exception_message)
    expected_msg = (
      "Error resolving binary request BinaryRequest(supportdir=supportdir, version=version, "
      "name=name, platform_dependent=False, external_url_generator=None, archiver=None): "
      "--binaries-baseurls is empty.")
    self.assertIn(expected_msg, the_raised_exception_message)

  def test_support_url_multi(self):
    """Tests to make sure existing base urls function as expected."""

    bootstrap_dir = '/tmp'

    with temporary_dir() as invalid_local_files, temporary_dir() as valid_local_files:
      binary_util = self._gen_binary_util(
        baseurls=[
          'BLATANTLY INVALID URL',
          'https://dl.bintray.com/pantsbuild/bin/reasonably-invalid-url',
          invalid_local_files,
          valid_local_files,
          'https://dl.bintray.com/pantsbuild/bin/another-invalid-url',
        ],
        bootstrap_dir=bootstrap_dir)

      binary_request = binary_util._make_deprecated_binary_request(
        supportdir='bin/protobuf',
        version='2.4.1',
        name='protoc')

      binary_path = binary_request.get_download_path(binary_util._host_platform())
      contents = b'proof'
      with safe_open(os.path.join(valid_local_files, binary_path), 'wb') as fp:
        fp.write(contents)

      binary_path_abs = os.path.join(bootstrap_dir, binary_path)

      self.assertEqual(binary_path_abs, binary_util.select(binary_request))

      self.assertEqual(contents, self._read_file(binary_path_abs))

  def test_support_url_fallback(self):
    """Tests fallback behavior with multiple support baseurls.

    Mocks up some dummy baseurls and then swaps out the URL reader to make sure urls are accessed
    and others are not.
    """
    fake_base, fake_url = self._fake_base, self._fake_url
    bases = [fake_base('apple'), fake_base('orange'), fake_base('banana')]

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

    binary_util = self._gen_binary_util(
      baseurls=bases,
      fetcher=fetcher)

    unseen = [item for item in fetcher.values() if item.startswith('SEEN ')]
    for supportdir, version, name in binaries.values():
      binary_path_abs = binary_util.select_binary(
        supportdir=supportdir,
        version=version,
        name=name)
      expected_content = 'SEEN {}'.format(name.upper())
      self.assertEqual(expected_content, self._read_file(binary_path_abs))
      unseen.remove(expected_content)
    self.assertEqual(0, len(unseen))  # Make sure we've seen all the SEENs.

  def test_select_binary_base_path_linux(self):
    def uname_func():
      return "linux", "dontcare1", "dontcare2", "dontcare3", "amd64"

    binary_util = self._gen_binary_util(uname_func=uname_func)

    binary_request = binary_util._make_deprecated_binary_request("supportdir", "version", "name")

    self.assertEquals("supportdir/linux/x86_64/version/name",
                      binary_util._get_download_path(binary_request))

  def test_select_binary_base_path_darwin(self):
    def uname_func():
      return "darwin", "dontcare1", "14.9", "dontcare2", "dontcare3",

    binary_util = self._gen_binary_util(uname_func=uname_func)

    binary_request = binary_util._make_deprecated_binary_request("supportdir", "version", "name")

    self.assertEquals("supportdir/mac/10.10/version/name",
                      binary_util._get_download_path(binary_request))

  def test_select_binary_base_path_missing_os(self):
    def uname_func():
      return "vms", "dontcare1", "999.9", "dontcare2", "VAX9"

    binary_util = self._gen_binary_util(uname_func=uname_func)

    with self.assertRaises(BinaryUtil.BinaryResolutionError) as cm:
      binary_util.select_binary("supportdir", "version", "name")

    the_raised_exception_message = str(cm.exception)

    self.assertIn(BinaryUtil.MissingMachineInfo.__name__, the_raised_exception_message)
    expected_msg = (
      "Error resolving binary request BinaryRequest(supportdir=supportdir, version=version, "
      "name=name, platform_dependent=True, external_url_generator=None, archiver=None): "
      "Pants could not resolve binaries for the current host: platform 'vms' was not recognized. "
      "Recognized platforms are: [u'darwin', u'linux'].")
    self.assertIn(expected_msg, the_raised_exception_message)

  def test_select_binary_base_path_missing_version(self):
    def uname_func():
      return "darwin", "dontcare1", "999.9", "dontcare2", "x86_64"

    binary_util = self._gen_binary_util(uname_func=uname_func)

    with self.assertRaises(BinaryUtil.BinaryResolutionError) as cm:
      binary_util.select_binary("mysupportdir", "myversion", "myname")
    the_raised_exception_message = str(cm.exception)

    self.assertIn(BinaryUtil.MissingMachineInfo.__name__, the_raised_exception_message)
    expected_msg = (
      "Error resolving binary request BinaryRequest(supportdir=mysupportdir, version=myversion, "
      "name=myname, platform_dependent=True, external_url_generator=None, archiver=None): Pants could not "
      "resolve binaries for the current host. Update --binaries-path-by-id to find binaries for "
      "the current host platform (u\'darwin\', u\'999\').\\n--binaries-path-by-id was:")
    self.assertIn(expected_msg, the_raised_exception_message)

  def test_select_script_missing_version(self):
    def uname_func():
      return "darwin", "dontcare1", "999.9", "dontcare2", "x86_64"

    binary_util = self._gen_binary_util(uname_func=uname_func)

    with self.assertRaises(BinaryUtil.BinaryResolutionError) as cm:
      binary_util.select_script("mysupportdir", "myversion", "myname")
    the_raised_exception_message = str(cm.exception)

    self.assertIn(BinaryUtil.MissingMachineInfo.__name__, the_raised_exception_message)
    expected_msg = (
      "Error resolving binary request BinaryRequest(supportdir=mysupportdir, version=myversion, "
      # platform_dependent=False when doing select_script()
      "name=myname, platform_dependent=False, external_url_generator=None, archiver=None): Pants "
      "could not resolve binaries for the current host. Update --binaries-path-by-id to find "
      "binaries for the current host platform (u\'darwin\', u\'999\').\\n--binaries-path-by-id was:")
    self.assertIn(expected_msg, the_raised_exception_message)

  def test_select_binary_base_path_override(self):
    def uname_func():
      return "darwin", "dontcare1", "100.99", "dontcare2", "t1000"

    binary_util = self._gen_binary_util(uname_func=uname_func,
                                        path_by_id={('darwin', '100'): ['skynet', '42']})

    binary_request = binary_util._make_deprecated_binary_request("supportdir", "version", "name")

    self.assertEquals("supportdir/skynet/42/version/name",
                      binary_util._get_download_path(binary_request))

  def test_external_url_generator(self):
    binary_util = self._gen_binary_util(baseurls=[])

    binary_request = BinaryRequest(
      supportdir='supportdir',
      version='version',
      name='name',
      platform_dependent=False,
      external_url_generator=ExternalUrlGenerator(),
      # TODO: test archiver!
      archiver=None)

    with self.assertRaises(BinaryUtil.BinaryResolutionError) as cm:
      binary_util.select(binary_request)
    the_raised_exception_message = str(cm.exception)

    self.assertIn(BinaryToolFetcher.BinaryNotFound.__name__, the_raised_exception_message)
    expected_msg = (
      "Error resolving binary request BinaryRequest(supportdir=supportdir, version=version, "
      "name=name, platform_dependent=False, "
      "external_url_generator=ExternalUrlGenerator(<example __str__()>), archiver=None): "
      "Failed to fetch name binary from any source: (Failed to fetch binary from "
      "https://example.com/some-binary: Fetch of https://example.com/some-binary failed with "
      "status code 404, Failed to fetch binary from https://example.com/same-binary: Fetch of "
      "https://example.com/same-binary failed with status code 404)'")
    self.assertIn(expected_msg, the_raised_exception_message)

  def test_disallowing_external_urls(self):
    binary_util = self._gen_binary_util(baseurls=[], allow_external_binary_tool_downloads=False)

    binary_request = binary_request = BinaryRequest(
      supportdir='supportdir',
      version='version',
      name='name',
      platform_dependent=False,
      external_url_generator=ExternalUrlGenerator(),
      # TODO: test archiver!
      archiver=None)

    with self.assertRaises(BinaryUtil.BinaryResolutionError) as cm:
      binary_util.select(binary_request)
    the_raised_exception_message = str(cm.exception)

    self.assertIn(BinaryUtil.NoBaseUrlsError.__name__, the_raised_exception_message)
    expected_msg = (
      "Error resolving binary request BinaryRequest(supportdir=supportdir, version=version, "
      "name=name, platform_dependent=False, "
      "external_url_generator=ExternalUrlGenerator(<example __str__()>), archiver=None): "
      "--binaries-baseurls is empty.")
    self.assertIn(expected_msg, the_raised_exception_message)
