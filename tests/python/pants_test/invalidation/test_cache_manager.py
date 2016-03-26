# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import shutil
import tempfile

from pants.invalidation.build_invalidator import CacheKey, CacheKeyGenerator
from pants.invalidation.cache_manager import InvalidationCacheManager, VersionedTarget
from pants_test.base_test import BaseTest


class AppendingCacheKeyGenerator(CacheKeyGenerator):
  """Generates cache keys for versions of target sets."""

  @staticmethod
  def combine_cache_keys(cache_keys):
    if len(cache_keys) == 1:
      return cache_keys[0]
    else:
      sorted_cache_keys = sorted(cache_keys)  # For commutativity.
      combined_id = ','.join([cache_key.id for cache_key in sorted_cache_keys])
      combined_hash = ','.join([cache_key.hash for cache_key in sorted_cache_keys])
      combined_num_sources = reduce(lambda x, y: x + y,
                                    [cache_key.num_sources for cache_key in sorted_cache_keys], 0)
      return CacheKey(combined_id, combined_hash, combined_num_sources)

  def key_for_target(self, target, sources=None, transitive=False, fingerprint_strategy=None):
    return CacheKey(target.id, target.id)

  def key_for(self, tid, sources):
    return CacheKey(tid, tid, len(sources))


def print_vt(vt):
  print('%d (%s) %s: [ %s ]' % (len(vt.targets), vt.cache_key, vt.valid, ', '.join(['%s(%s)' % (v.id, v.cache_key) for v in vt.versioned_targets])))


class InvalidationCacheManagerTest(BaseTest):

  class TestInvalidationCacheManager(InvalidationCacheManager):

    def __init__(self, tmpdir):
      super(InvalidationCacheManagerTest.TestInvalidationCacheManager, self).__init__(
        AppendingCacheKeyGenerator(), tmpdir, True)

  def setUp(self):
    super(InvalidationCacheManagerTest, self).setUp()
    self._dir = tempfile.mkdtemp()
    self.cache_manager = InvalidationCacheManagerTest.TestInvalidationCacheManager(self._dir)

  def tearDown(self):
    shutil.rmtree(self._dir, ignore_errors=True)
    super(InvalidationCacheManagerTest, self).tearDown()

  def make_vts(self, target):
    return VersionedTarget(self.cache_manager, target, target.id)

  def test_check_marks_all_as_invalid_by_default(self):
    a = self.make_target(':a', dependencies=[])
    b = self.make_target(':b', dependencies=[a])
    c = self.make_target(':c', dependencies=[b])
    d = self.make_target(':d', dependencies=[c, a])
    e = self.make_target(':e', dependencies=[d])

    targets = [a, b, c, d, e]

    ic = self.cache_manager.check(targets)

    all_vts = ic.all_vts
    invalid_vts = ic.invalid_vts

    self.assertEquals(5, len(invalid_vts))
    self.assertEquals(5, len(all_vts))
    vts_targets = [vt.targets[0] for vt in all_vts]
    self.assertEquals(set(targets), set(vts_targets))
