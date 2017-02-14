# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.base.project_tree import Dir, File
from pants.engine.nodes import Runnable
from pants.engine.storage import Cache, InvalidKeyError, Storage


def _runnable(an_arg):
  return an_arg


class PickleableException(Exception):
  def __eq__(self, other):
    return type(self) == type(other)


class StorageTest(unittest.TestCase):
  TEST_KEY = b'hello'
  TEST_VALUE = b'world'

  TEST_PATH = File('/foo')
  TEST_PATH2 = Dir('/bar')

  class SomeException(Exception): pass

  def setUp(self):
    self.storage = Storage.create()
    self.result = 'something'
    self.request = Runnable(func=_runnable, args=('this is an arg',), cacheable=True)

  def test_storage(self):
    key = self.storage.put(self.TEST_PATH)
    self.assertEquals(self.TEST_PATH, self.storage.get(key))

    with self.assertRaises(InvalidKeyError):
      self.assertFalse(self.storage.get(self.TEST_KEY))

  def test_storage_key_mappings(self):
    key1 = self.storage.put(self.TEST_PATH)
    key2 = self.storage.put(self.TEST_PATH2)
    self.storage.add_mapping(key1, key2)
    self.assertEquals(key2, self.storage.get_mapping(key1))

    # key2 isn't mapped to any other key.
    self.assertIsNone(self.storage.get_mapping(key2))


class CacheTest(unittest.TestCase):

  def setUp(self):
    """Setup cache as well as request and result."""
    self.storage = Storage.create()
    self.cache = Cache.create(storage=self.storage)
    self.request = Runnable(func=_runnable, args=('this is an arg',), cacheable=True)
    self.result = 'something'

  def test_cache(self):
    """Verify get and put."""
    self.assertIsNone(self.cache.get(self.request)[1])
    self._assert_hits_misses(hits=0, misses=1)

    request_key = self.storage.put_state(self.request)
    self.cache.put(request_key, self.result)

    self.assertEquals(self.result, self.cache.get(self.request)[1])
    self._assert_hits_misses(hits=1, misses=1)

  def test_failure_to_update_mapping(self):
    """Verify we can access cached result only if we save both result and the key mapping."""
    # This places result to the main storage without saving to key mapping. This
    # simulates error might happen for saving key mapping after successfully saving the result.
    self.cache._storage.put(self.result)

    self.assertIsNone(self.cache.get(self.request)[1])
    self._assert_hits_misses(hits=0, misses=1)

  def _assert_hits_misses(self, hits, misses):
    self.assertEquals(hits, self.cache.get_stats().hits)
    self.assertEquals(misses, self.cache.get_stats().misses)
    self.assertEquals(hits+misses, self.cache.get_stats().total)
