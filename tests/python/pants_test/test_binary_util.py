# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binary_util import BinaryUtil
from pants_test.base_test import BaseTest


class BinaryUtilTest(BaseTest):
  """Tests binary_util's pants_support_baseurls handling."""


  class LambdaReader(object):
    """Class which pretends to be an input stream, but is actually a lambda function."""
    def __init__(self, func):
      self._func = func

    def __call__(self):
      return self._func()

    def read(self):
      return self()

    def __enter__(self, a=None, b=None, c=None, d=None):
      return self

    def __exit__(self, a=None, b=None, c=None, d=None):
      pass

  class MapReader(object):
    """Class which pretends to be a url stream opener, but is actually a dictionary."""
    def __init__(self, read_map):
      self._map = read_map

    def __call__(self, key):
      if not key in self._map:
        raise IOError("404: Virtual URL '{key}' does not exist.".format(key=key))
      value = self._map[key]
      return BinaryUtilTest.LambdaReader(lambda: value)

    def keys(self):
      return self._map.keys()

    def values(self):
      return self._map.values()

    def __getitem__(self, key):
      return self._map[key] # Vanilla internal map access (without lambda shenanigans).

  def setUp(self):
    super(BinaryUtilTest, self).setUp()

  @classmethod
  def _fake_base(cls, name):
    return 'fake-url-{name}'.format(name=name)

  @classmethod
  def _fake_url(cls, binaries, base, binary_key):
    supportdir, version, name = binaries[binary_key]
    return '{base}/{binary}'.format(base=base,
                                    binary=BinaryUtil.select_binary_base_path(
                                      supportdir, version, binary_key))

  def test_nobases(self):
    """Tests exception handling if build support urls are improperly specified."""
    try:
      with BinaryUtil('bin/protobuf', '2.4.1', [], 30, '/tmp').select_binary_stream('protoc') as stream:
        self.fail('We should have gotten a "NoBaseUrlsError".')
    except BinaryUtil.NoBaseUrlsError as e:
      pass # expected

  def test_support_url_multi(self):
    """Tests to make sure existing base urls function as expected."""
    count = 0
    with BinaryUtil(
      supportdir='bin/protobuf',
      version='2.4.1',
      baseurls=[
      'BLATANTLY INVALID URL',
      'https://dl.bintray.com/pantsbuild/bin/reasonably-invalid-url',
      'https://dl.bintray.com/pantsbuild/bin/build-support',
      'https://dl.bintray.com/pantsbuild/bin/build-support', # Test duplicate entry handling.
      'https://dl.bintray.com/pantsbuild/bin/another-invalid-url',
    ],
      timeout_secs=30,
      bootstrapdir='/tmp').select_binary_stream('protoc') as stream:
      stream()
      count += 1
    self.assertEqual(count, 1)

  def test_support_url_fallback(self):
    """Tests fallback behavior with multiple support baseurls.

    Mocks up some dummy baseurls and then swaps out the URL reader to make sure urls are accessed
    and others are not.
    """
    fake_base, fake_url = self._fake_base, self._fake_url
    binaries = {
      'protoc': ('bin/protobuf', '2.4.1', 'protoc',),
      'ivy': ('bin/ivy', '4.3.7', 'ivy',),
      'bash': ('bin/bash', '4.4.3', 'bash',),
    }
    bases = [fake_base('apple'), fake_base('orange'), fake_base('banana'),]
    reader = self.MapReader({
      fake_url(binaries, bases[0], 'protoc'): 'SEEN PROTOC',
      fake_url(binaries, bases[0], 'ivy'): 'SEEN IVY',
      fake_url(binaries, bases[1], 'bash'): 'SEEN BASH',
      fake_url(binaries, bases[1], 'protoc'): 'UNSEEN PROTOC 1',
      fake_url(binaries, bases[2], 'protoc'): 'UNSEEN PROTOC 2',
      fake_url(binaries, bases[2], 'ivy'): 'UNSEEN IVY 2',
    })

    unseen = [item for item in reader.values() if item.startswith('SEEN ')]
    for key in binaries:
      supportdir, version, name = binaries[key]
      with BinaryUtil(supportdir, version, bases, 30, '/tmp').select_binary_stream(
          key,
          url_opener=reader) as stream:
        self.assertEqual(stream(), 'SEEN ' + key.upper())
        unseen.remove(stream())
    self.assertEqual(0, len(unseen)) # Make sure we've seen all the SEENs.
