# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from contextlib import closing

from pants.base.project_tree import Dir, File
from pants.engine.scheduler import StepRequest, StepResult
from pants.engine.storage import Cache, InvalidKeyError, Key, Lmdb, Storage


class StorageTest(unittest.TestCase):
  TEST_KEY = b'hello'
  TEST_VALUE = b'world'

  TEST_PATH = File('/foo')
  TEST_PATH2 = Dir('/bar')

  class SomeException(Exception): pass

  def setUp(self):
    self.storage = Storage.create()
    self.result = StepResult(state='something')
    self.request = StepRequest(step_id=123,
                               node='some node',
                               dependencies={'some dep': 'some state',
                                             'another dep': 'another state'},
                               inline_nodes=False,
                               project_tree='some project tree')

  def test_lmdb_key_value_store(self):
    lmdb = Lmdb.create()[0]
    with closing(lmdb) as kvs:
      # Initially key does not exist.
      self.assertFalse(kvs.get(self.TEST_KEY))

      # Now write a key value pair and read back.
      written = kvs.put(self.TEST_KEY, self.TEST_VALUE)
      self.assertTrue(written)
      self.assertEquals(self.TEST_VALUE, kvs.get(self.TEST_KEY).getvalue())

      # Write the same key again will not overwrite.
      self.assertFalse(kvs.put(self.TEST_KEY, self.TEST_VALUE))

  def test_storage(self):
    with closing(self.storage) as storage:
      key = storage.put(self.TEST_PATH)
      self.assertEquals(self.TEST_PATH, storage.get(key))
      # The deserialized blob is equal by not the same as the input data.
      self.assertFalse(storage.get(key) is self.TEST_PATH)

      # Any other keys won't exist in the subjects.
      self.assertNotEqual(self.TEST_KEY, key)

      with self.assertRaises(InvalidKeyError):
        self.assertFalse(storage.get(self.TEST_KEY))

      # Verify key and value's types must match.
      key._type = str
      with self.assertRaises(ValueError):
        storage.get(key)

  def test_storage_key_mappings(self):
    with closing(self.storage) as storage:
      key1 = storage.put(self.TEST_PATH)
      key2 = storage.put(self.TEST_PATH2)
      storage.add_mapping(key1, key2)
      self.assertEquals(key2, storage.get_mapping(key1))

      # key2 isn't mapped to any other key.
      self.assertIsNone(storage.get_mapping(key2))

  def test_key_for_request(self):
    with closing(self.storage) as storage:
      keyed_request = storage.key_for_request(self.request)
      for dep, dep_state in keyed_request.dependencies.items():
        self.assertEquals(Key, type(dep))
        self.assertEquals(Key, type(dep_state))
      self.assertIs(self.request.node, keyed_request.node)
      self.assertIs(self.request.project_tree, keyed_request.project_tree)

      self.assertEquals(keyed_request, storage.key_for_request(keyed_request))

  def test_resolve_request(self):
    with closing(self.storage) as storage:
      keyed_request = storage.key_for_request(self.request)
      resolved_request = storage.resolve_request(keyed_request)
      self.assertEquals(self.request, resolved_request)
      self.assertIsNot(self.request, resolved_request)

      self.assertEquals(resolved_request, self.storage.resolve_request(resolved_request))

  def test_key_for_result(self):
    with closing(self.storage) as storage:
      keyed_result = storage.key_for_result(self.result)
      self.assertEquals(Key, type(keyed_result.state))

      self.assertEquals(keyed_result, storage.key_for_result(keyed_result))

  def test_resolve_result(self):
    with closing(self.storage) as storage:
      keyed_result = storage.key_for_result(self.result)
      resolved_result = storage.resolve_result(keyed_result)
      self.assertEquals(self.result, resolved_result)
      self.assertIsNot(self.result, resolved_result)

      self.assertEquals(resolved_result, self.storage.resolve_result(resolved_result))


class CacheTest(unittest.TestCase):

  def setUp(self):
    """Setup cache as well as request and result."""
    self.storage = Storage.create()
    self.cache = Cache.create(storage=self.storage)
    request = StepRequest(step_id=123,
                          node='some node',
                          dependencies={'some dep': 'some state',
                                        'another dep': 'another state'},
                          inline_nodes=False,
                          project_tree='some project tree')
    self.result = StepResult(state='something')
    self.keyed_request = self.storage.key_for_request(request)

  def test_cache(self):
    """Verify get and put."""
    with closing(self.cache):
      self.assertIsNone(self.cache.get(self.keyed_request))
      self._assert_hits_misses(hits=0, misses=1)

      self.cache.put(self.keyed_request, self.result)

      self.assertEquals(self.result, self.cache.get(self.keyed_request))
      self.assertIsNot(self.result, self.cache.get(self.keyed_request))
      self._assert_hits_misses(hits=2, misses=1)

  def test_failure_to_update_mapping(self):
    """Verify we can access cached result only if we save both result and the key mapping."""
    with closing(self.cache):
      # This places result to the main storage without saving to key mapping. This
      # simulates error might happen for saving key mapping after successfully saving the result.
      self.cache._storage.put(self.result)

      self.assertIsNone(self.cache.get(self.keyed_request))
      self._assert_hits_misses(hits=0, misses=1)

  def _assert_hits_misses(self, hits, misses):
    self.assertEquals(hits, self.cache.get_stats().hits)
    self.assertEquals(misses, self.cache.get_stats().misses)
    self.assertEquals(hits+misses, self.cache.get_stats().total)
