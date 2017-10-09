# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import tempfile
import unittest
from contextlib import contextmanager

from pants.invalidation.build_invalidator import BuildInvalidator, CacheKey
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_rmtree
from pants_test.subsystem.subsystem_util import init_subsystem


class CacheKeyTest(unittest.TestCase):
  def test_equality(self):
    self.assertEqual(CacheKey(id='1', hash='a'), CacheKey(id='1', hash='a'))
    self.assertEqual(CacheKey.uncacheable(id='1'), CacheKey.uncacheable(id='1'))

    self.assertNotEqual(CacheKey(id='1', hash='a'), CacheKey(id='2', hash='a'))
    self.assertNotEqual(CacheKey.uncacheable(id='1'), CacheKey.uncacheable(id='2'))

    self.assertNotEqual(CacheKey(id='1', hash='a'), CacheKey(id='1', hash='b'))

  def test_combine_single(self):
    key = CacheKey(id='a', hash='b')
    self.assertIs(key, CacheKey.combine_cache_keys([key]))

  def test_combine_multiple(self):
    key1 = CacheKey(id='1', hash='a')
    key2 = CacheKey(id='2', hash='b')
    combined_key = CacheKey.combine_cache_keys([key1, key2])

    self.assertNotEqual(key1, combined_key)
    self.assertNotEqual(key2, combined_key)
    self.assertEqual(combined_key, CacheKey.combine_cache_keys([key1, key2]))

  def test_cacheable(self):
    self.assertTrue(CacheKey(id='1', hash='a').cacheable)
    self.assertFalse(CacheKey.uncacheable(id='1').cacheable)


class BaseBuildInvalidatorTest(unittest.TestCase):
  @staticmethod
  def ensure_key_id(key_id):
    return key_id or 'a.target'

  @classmethod
  def cache_key(cls, key_id=None, key_hash=None):
    return CacheKey(id=cls.ensure_key_id(key_id), hash=key_hash or '42')

  @classmethod
  def uncacheable_cache_key(cls, key_id=None):
    return CacheKey.uncacheable(id=cls.ensure_key_id(key_id))

  @staticmethod
  def update_hash(cache_key, new_hash):
    return CacheKey(id=cache_key.id, hash=new_hash)


class BuildInvalidatorTest(BaseBuildInvalidatorTest):
  @contextmanager
  def invalidator(self):
    with temporary_dir() as root:
      yield BuildInvalidator(root)

  def test_cache_key_previous(self):
    with self.invalidator() as invalidator:
      key = self.cache_key()
      self.assertIsNone(invalidator.previous_key(key))
      invalidator.update(key)
      self.assertFalse(invalidator.needs_update(key))
      self.assertEqual(key, invalidator.previous_key(key))

  def test_cache_key_previous_uncacheable(self):
    with self.invalidator() as invalidator:
      key = self.uncacheable_cache_key()
      self.assertIsNone(invalidator.previous_key(key))
      invalidator.update(key)
      self.assertTrue(invalidator.needs_update(key))
      self.assertIsNone(invalidator.previous_key(key))

  def test_needs_update_missing_key(self):
    with self.invalidator() as invalidator:
      key = self.cache_key()
      self.assertTrue(invalidator.needs_update(key))

  def test_needs_update_missing_key_uncacheable(self):
    with self.invalidator() as invalidator:
      key = self.uncacheable_cache_key()
      self.assertTrue(invalidator.needs_update(key))

  def test_needs_update_after_change(self):
    with self.invalidator() as invalidator:
      key = self.cache_key()
      self.assertTrue(invalidator.needs_update(key))
      invalidator.update(key)
      self.assertFalse(invalidator.needs_update(key))
      key = self.update_hash(key, new_hash='1/137')
      self.assertTrue(invalidator.needs_update(key))
      invalidator.update(key)
      self.assertFalse(invalidator.needs_update(key))

  def test_needs_update_after_change_uncacheable(self):
    with self.invalidator() as invalidator:
      key = self.uncacheable_cache_key()
      self.assertTrue(invalidator.needs_update(key))
      invalidator.update(key)
      self.assertTrue(invalidator.needs_update(key))

  def test_force_invalidate(self):
    with self.invalidator() as invalidator:
      key1 = self.cache_key(key_id='1', key_hash='1')
      key2 = self.cache_key(key_id='2', key_hash='2')
      invalidator.update(key1)
      invalidator.update(key2)
      self.assertFalse(invalidator.needs_update(key1))
      self.assertFalse(invalidator.needs_update(key2))
      invalidator.force_invalidate(key1)
      self.assertTrue(invalidator.needs_update(key1))
      self.assertFalse(invalidator.needs_update(key2))

  def test_force_invalidate_all(self):
    with self.invalidator() as invalidator:
      key1 = self.cache_key(key_id='1', key_hash='1')
      key2 = self.cache_key(key_id='2', key_hash='2')
      invalidator.update(key1)
      invalidator.update(key2)
      self.assertFalse(invalidator.needs_update(key1))
      self.assertFalse(invalidator.needs_update(key2))
      invalidator.force_invalidate_all()
      self.assertTrue(invalidator.needs_update(key1))
      self.assertTrue(invalidator.needs_update(key2))


class BuildInvalidatorFactoryTest(BaseBuildInvalidatorTest):
  def setUp(self):
    pants_workdir = tempfile.mkdtemp()
    self.addCleanup(safe_rmtree, pants_workdir)

    init_subsystem(BuildInvalidator.Factory, options={'': {'pants_workdir': pants_workdir}})
    self.root_invalidator = BuildInvalidator.Factory.create()
    self.scoped_invalidator1 = BuildInvalidator.Factory.create(build_task='gen')
    self.scoped_invalidator2 = BuildInvalidator.Factory.create(build_task='resolve')

    self.key = self.cache_key()

  def test_root(self):
    self.scoped_invalidator1.update(self.key)
    self.scoped_invalidator2.update(self.key)
    self.assertFalse(self.scoped_invalidator1.needs_update(self.key))
    self.assertFalse(self.scoped_invalidator2.needs_update(self.key))

    self.root_invalidator.force_invalidate_all()

    self.assertTrue(self.scoped_invalidator1.needs_update(self.key))
    self.assertTrue(self.scoped_invalidator2.needs_update(self.key))

  def test_build_task_scoped(self):
    self.scoped_invalidator1.update(self.key)
    self.scoped_invalidator2.update(self.key)
    self.assertFalse(self.scoped_invalidator1.needs_update(self.key))
    self.assertFalse(self.scoped_invalidator2.needs_update(self.key))

    self.scoped_invalidator1.force_invalidate_all()

    self.assertTrue(self.scoped_invalidator1.needs_update(self.key))
    self.assertFalse(self.scoped_invalidator2.needs_update(self.key))
