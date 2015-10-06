# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import errno
import hashlib
import os
from collections import namedtuple

from pants.base.hash_utils import hash_all
from pants.build_graph.target import Target
from pants.fs.fs import safe_filename
from pants.util.dirutil import safe_mkdir


# A CacheKey represents some version of a set of targets.
#  - id identifies the set of targets.
#  - hash is a fingerprint of all invalidating inputs to the build step, i.e., it uniquely
#    determines a given version of the artifacts created when building the target set.
#  - num_chunking_units: The number of "units" of chunking the payloads together contribute
#    to the chunking algorithm.  Right now this is used to count the number of source files
#    in a scala target set for breaking up zinc invocations.

CacheKey = namedtuple('CacheKey', ['id', 'hash', 'num_chunking_units'])


# Bump this to invalidate all existing keys in artifact caches across all pants deployments in the
# world. Do this if you've made a change that invalidates existing artifacts, e.g.,  fixed a bug
# that caused bad artifacts to be cached.
GLOBAL_CACHE_KEY_GEN_VERSION = '7'


class CacheKeyGenerator(object):
  """Generates cache keys for versions of target sets."""

  @staticmethod
  def combine_cache_keys(cache_keys):
    """Returns a cache key for a list of target sets that already have cache keys.

    This operation is 'idempotent' in the sense that if cache_keys contains a single key
    then that key is returned.

    Note that this operation is commutative but not associative.  We use the term 'combine' rather
    than 'merge' or 'union' to remind the user of this. Associativity is not a necessary property,
    in practice.
    """
    if len(cache_keys) == 1:
      return cache_keys[0]
    else:
      combined_id = Target.maybe_readable_combine_ids(cache_key.id for cache_key in cache_keys)
      combined_hash = hash_all(sorted(cache_key.hash for cache_key in cache_keys))
      summed_chunking_units = sum([cache_key.num_chunking_units for cache_key in cache_keys])
      return CacheKey(combined_id, combined_hash, summed_chunking_units)

  def __init__(self, cache_key_gen_version=None):
    """
    cache_key_gen_version - If provided, added to all cache keys. Allows you to invalidate
      all cache keys in a single pants repo, by changing this value in config.
    """

    self._cache_key_gen_version = '_'.join([cache_key_gen_version or '',
                                            GLOBAL_CACHE_KEY_GEN_VERSION])

  def key_for_target(self, target, transitive=False, fingerprint_strategy=None):
    """Get a key representing the given target and its sources.

    A key for a set of targets can be created by calling combine_cache_keys()
    on the target's individual cache keys.

    :target: The target to create a CacheKey for.
    :transitive: Whether or not to include a fingerprint of all of :target:'s dependencies.
    :fingerprint_strategy: A FingerprintStrategy instance, which can do per task, finer grained
      fingerprinting of a given Target.
    """

    hasher = hashlib.sha1()
    hasher.update(self._cache_key_gen_version)
    key_suffix = hasher.hexdigest()[:12]
    if transitive:
      target_key = target.transitive_invalidation_hash(fingerprint_strategy)
    else:
      target_key = target.invalidation_hash(fingerprint_strategy)
    if target_key is not None:
      full_key = '{target_key}_{key_suffix}'.format(target_key=target_key, key_suffix=key_suffix)
      return CacheKey(target.id, full_key, target.num_chunking_units)
    else:
      return None


# A persistent map from target set to cache key, which is a fingerprint of all
# the inputs to the current version of that target set. That cache key can then be used
# to look up build artifacts in an artifact cache.
class BuildInvalidator(object):
  """Invalidates build targets based on the SHA1 hash of source files and other inputs."""

  def __init__(self, root):
    self._root = os.path.join(root, GLOBAL_CACHE_KEY_GEN_VERSION)
    safe_mkdir(self._root)

  def needs_update(self, cache_key):
    """Check if the given cached item is invalid.

    :param cache_key: A CacheKey object (as returned by CacheKeyGenerator.key_for().
    :returns: True if the cached version of the item is out of date.
    """
    return self._read_sha(cache_key) != cache_key.hash

  def update(self, cache_key):
    """Makes cache_key the valid version of the corresponding target set.

    :param cache_key: A CacheKey object (typically returned by CacheKeyGenerator.key_for()).
    """
    self._write_sha(cache_key)

  def force_invalidate_all(self):
    """Force-invalidates all cached items."""
    safe_mkdir(self._root, clean=True)

  def force_invalidate(self, cache_key):
    """Force-invalidate the cached item."""
    try:
      os.unlink(self._sha_file(cache_key))
    except OSError as e:
      if e.errno != errno.ENOENT:
        raise

  def existing_hash(self, id):
    """Returns the existing hash for the specified id.

    Returns None if there is no existing hash for this id.
    """
    return self._read_sha_by_id(id)

  def _sha_file(self, cache_key):
    return self._sha_file_by_id(cache_key.id)

  def _sha_file_by_id(self, id):
    return os.path.join(self._root, safe_filename(id, extension='.hash'))

  def _write_sha(self, cache_key):
    with open(self._sha_file(cache_key), 'w') as fd:
      fd.write(cache_key.hash)

  def _read_sha(self, cache_key):
    return self._read_sha_by_id(cache_key.id)

  def _read_sha_by_id(self, id):
    try:
      with open(self._sha_file_by_id(id), 'rb') as fd:
        return fd.read().strip()
    except IOError as e:
      if e.errno != errno.ENOENT:
        raise
      return None  # File doesn't exist.
