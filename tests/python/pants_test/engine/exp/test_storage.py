# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
from contextlib import closing

from pants.engine.exp.fs import Path
from pants.engine.exp.storage import InvalidKeyError, Lmdb, Storage


class StorageTest(unittest.TestCase):
  TEST_KEY = b'hello'
  TEST_VALUE = b'world'

  TEST_PATH = Path('/foo')

  def test_lmdb_key_value_store(self):
    with closing(Lmdb()) as kvs:
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
