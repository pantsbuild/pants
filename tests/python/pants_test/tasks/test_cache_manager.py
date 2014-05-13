# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import shutil
import tempfile

from pants.base.build_invalidator import CacheKey, CacheKeyGenerator
from pants.tasks.cache_manager import CacheManager, InvalidationCheck, VersionedTarget
from pants_test.testutils.base_mock_target_test import BaseMockTargetTest
from pants_test.testutils.mock_target import MockTarget


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
      combined_num_sources = reduce(lambda x, y: x + y, [cache_key.num_sources for cache_key in sorted_cache_keys], 0)
      return CacheKey(combined_id, combined_hash, combined_num_sources, [])

  def key_for_target(self, target, sources=None, fingerprint_extra=None):
    return CacheKey(target.id, target.id, target.num_sources, [])

  def key_for(self, tid, sources):
    return CacheKey(tid, tid, len(sources), [])


def print_vt(vt):
  print('%d (%s) %s: [ %s ]' % (len(vt.targets), vt.cache_key, vt.valid, ', '.join(['%s(%s)' % (v.id, v.cache_key) for v in vt.versioned_targets])))


class CacheManagerTest(BaseMockTargetTest):
  class TestCacheManager(CacheManager):
    def __init__(self, tmpdir):
      CacheManager.__init__(self, AppendingCacheKeyGenerator(), tmpdir, True, None, False)

  def setUp(self):
    self._dir = tempfile.mkdtemp()
    self.cache_manager = CacheManagerTest.TestCacheManager(self._dir)

  def tearDown(self):
    shutil.rmtree(self._dir, ignore_errors=True)

  def make_vts(self, target):
    return VersionedTarget(self.cache_manager, target, target.id)

  def test_partition(self):
    # Set up test targets.
    a = MockTarget('a', [], 1)
    b = MockTarget('b', [a], 1)
    c = MockTarget('c', [b], 1)
    d = MockTarget('d', [c, a], 1)
    e = MockTarget('e', [d], 1)

    targets = [a, b, c, d, e]

    def print_partitions(partitions):
      strs = []
      for partition in partitions:
        strs.append('(%s)' % ', '.join([t.id for t in partition.targets]))
      print('[%s]' % ' '.join(strs))

    # Verify basic data structure soundness.
    all_vts = self.cache_manager._sort_and_validate_targets(targets)
    invalid_vts = filter(lambda vt: not vt.valid, all_vts)
    self.assertEquals(5, len(invalid_vts))
    self.assertEquals(5, len(all_vts))
    vts_targets = [vt.targets[0] for vt in all_vts]
    self.assertEquals(set(targets), set(vts_targets))

    # Test a simple partition.
    ic = InvalidationCheck(all_vts, [], 3)
    partitioned = ic.all_vts_partitioned
    print_partitions(partitioned)

    # Several correct partitionings are possible, but in all cases 4 1-source targets will be
    # added to the first partition before it exceeds the limit of 3, and the final target will
    # be in a partition by itself.
    self.assertEquals(2, len(partitioned))
    self.assertEquals(4, len(partitioned[0].targets))
    self.assertEquals(1, len(partitioned[1].targets))

    # Test partition with colors.
    red = 'red'
    blue = 'blue'

    colors = {
      all_vts[0]: blue,
      all_vts[1]: red,
      all_vts[2]: red,
      all_vts[3]: red,
      all_vts[4]: blue
    }

    # As a reference, we partition without colors.
    ic = InvalidationCheck(all_vts, [], 2)
    partitioned = ic.all_vts_partitioned
    print_partitions(partitioned)

    self.assertEquals(2, len(partitioned))
    self.assertEquals(3, len(partitioned[0].targets))
    self.assertEquals(2, len(partitioned[1].targets))

    # Now apply color restrictions.
    ic = InvalidationCheck(all_vts, [], 2, vt_colors=colors)
    partitioned = ic.all_vts_partitioned
    print_partitions(partitioned)

    self.assertEquals(3, len(partitioned))
    self.assertEquals(1, len(partitioned[0].targets))
    self.assertEquals(3, len(partitioned[1].targets))
    self.assertEquals(1, len(partitioned[2].targets))
