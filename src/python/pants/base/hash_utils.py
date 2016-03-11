# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib


def hash_all(strs, digest=None):
  """Returns a hash of the concatenation of all the strings in strs.

  If a hashlib message digest is not supplied a new sha1 message digest is used.
  """
  digest = digest or hashlib.sha1()
  for s in strs:
    digest.update(s)
  return digest.hexdigest()


def hash_file(path, digest=None):
  """Hashes the contents of the file at the given path and returns the hash digest in hex form.

  If a hashlib message digest is not supplied a new sha1 message digest is used.
  """
  digest = digest or hashlib.sha1()
  with open(path, 'rb') as fd:
    s = fd.read(8192)
    while s:
      digest.update(s)
      s = fd.read(8192)
  return digest.hexdigest()


class Sharder(object):
  """Assigns strings to shards pseudo-randomly, but stably."""

  class InvalidShardSpec(Exception):
    """Indicates an invalid shard spec."""

    def __init__(self, shard_spec):
      """
      :param string shard_spec: A string of the form M/N where M, N are ints and 0 <= M < N.
      """
      super(Sharder.InvalidShardSpec, self).__init__(
          "Invalid shard spec '{}', should be of the form M/N, where M, N are ints "
          "and 0 <= M < N.".format(shard_spec))

  @staticmethod
  def compute_shard(s, mod):
    """Computes the mod-hash of the given string, using a sha1 hash.

    :param string s: The string to compute a shard for.
    """
    return int(hash_all([s]), 16) % mod

  def __init__(self, shard_spec):
    """
    :param string shard_spec: A string of the form M/N where M, N are ints and 0 <= M < N.
    """
    def ensure_int(s):
      try:
        return int(s)
      except ValueError:
        raise self.InvalidShardSpec(shard_spec)

    if shard_spec is None:
      raise self.InvalidShardSpec('None')
    shard_str, _, nshards_str = shard_spec.partition('/')
    self._shard = ensure_int(shard_str)
    self._nshards = ensure_int(nshards_str)

    if self._shard < 0 or self._shard >= self._nshards:
      raise self.InvalidShardSpec(shard_spec)

  def is_in_shard(self, s):
    """Returns True iff the string s is in this shard.

    :param string s: The string to check.
    """
    return self.compute_shard(s, self._nshards) == self._shard

  @property
  def shard(self):
    return self._shard

  @property
  def nshards(self):
    return self._nshards
