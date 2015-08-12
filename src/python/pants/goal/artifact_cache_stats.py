# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict, namedtuple

from pants.util.dirutil import safe_mkdir


# Lists of target addresses.
CacheStat = namedtuple('CacheStat', ['hit_targets', 'miss_targets'])


class ArtifactCacheStats(object):
  """Tracks the hits and misses in the artifact cache.

  If dir is specified, writes the hits and misses to files in that dir."""

  def __init__(self, dir=None):
    def init_stat():
      return CacheStat([], [])
    self.stats_per_cache = defaultdict(init_stat)
    self._dir = dir
    safe_mkdir(self._dir)

  def add_hit(self, cache_name, tgt):
    self._add_stat(0, cache_name, tgt)

  def add_miss(self, cache_name, tgt):
    self._add_stat(1, cache_name, tgt)

  def get_all(self):
    """Returns the cache stats as a list of dicts."""
    ret = []
    for cache_name, stat in self.stats_per_cache.items():
      ret.append({
        'cache_name': cache_name,
        'num_hits': len(stat.hit_targets),
        'num_misses': len(stat.miss_targets),
        'hits': stat.hit_targets,
        'misses': stat.miss_targets
      })
    return ret

  # hit_or_miss is the appropriate index in CacheStat, i.e., 0 for hit, 1 for miss.
  def _add_stat(self, hit_or_miss, cache_name, tgt):
    self.stats_per_cache[cache_name][hit_or_miss].append(tgt.address.reference())
    if self._dir and os.path.exists(self._dir):  # Check existence in case of a clean-all.
      suffix = 'misses' if hit_or_miss else 'hits'
      with open(os.path.join(self._dir, '{}.{}'.format(cache_name, suffix)), 'a') as f:
        f.write(tgt.address.reference())
        f.write('\n')
