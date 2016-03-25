# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from contextlib import closing

from pants.build_graph.address import Address
from pants.engine.exp.fs import Path
from pants.engine.exp.graph import BuildFilePaths
from pants.engine.exp.nodes import SelectNode
from pants.engine.exp.scheduler import Return, StepRequest, StepResult
from pants.engine.exp.storage import Cache, InMemoryDb, InvalidKeyError, Lmdb, Storage
from pants.engine.exp.struct import Variants


class StorageTest(unittest.TestCase):
  TEST_KEY = b'hello'
  TEST_VALUE = b'world'

  TEST_PATH = Path('/foo')
  TEST_PATH2 = Path('/bar')

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
    with closing(Storage.create(in_memory=True)) as storage:
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
    with closing(Storage.create(in_memory=True)) as storage:
      key1 = storage.put(self.TEST_PATH)
      key2 = storage.put(self.TEST_PATH2)
      storage.add_mapping(key1, key2)
      self.assertEquals(key2, storage.get_mapping(key1))

      # key2 isn't mapped to any other key.
      self.assertIsNone(storage.get_mapping(key2))


class CacheTest(unittest.TestCase):

  def setUp(self):
    """Setup cache as well as request and result."""
    self.storage = Storage.create(in_memory=True)
    self.cache = Cache.create(storage=self.storage)

    self.simple = Address.parse('a/b')
    self.build_file = BuildFilePaths([Path('a/b/BLD.json')])

    subject_key = self.storage.put(self.simple)
    self.node = SelectNode(subject_key, Path, None, None)
    self.dep_node = SelectNode(subject_key, Variants, None, None)
    self.dep_state = self.storage.put(Return(None))

    self.request = StepRequest(1, self.node, {self.dep_node: self.dep_state}, None)
    self.result = StepResult(self.storage.put(self.simple))

  def test_cache(self):
    """Verify get and put."""
    with closing(self.cache):
      self.assertIsNone(self.cache.get(self.request))
      self._assert_hits_misses(hits=0, misses=1)

      self.cache.put(self.request, self.result)

      self.assertEquals(self.result, self.cache.get(self.request))
      self.assertIsNot(self.result, self.cache.get(self.request))
      self._assert_hits_misses(hits=2, misses=1)

  def test_failure_to_update_mapping(self):
    """Verify we can access cached result only if we save both result and the key mapping."""
    with closing(self.cache):
      # This places result to the main storage without saving to key mapping. This
      # simulates error might happen for saving key mapping after successfully saving the result.
      self.cache._storage.put(self.result)

      self.assertIsNone(self.cache.get(self.request))
      self._assert_hits_misses(hits=0, misses=1)

  def _assert_hits_misses(self, hits, misses):
    self.assertEquals(hits, self.cache.get_stats().hits)
    self.assertEquals(misses, self.cache.get_stats().misses)
    self.assertEquals(hits+misses, self.cache.get_stats().total)
