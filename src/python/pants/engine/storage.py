# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import cPickle as pickle
import cStringIO as StringIO
from binascii import hexlify
from collections import Counter
from contextlib import closing
from hashlib import sha1
from struct import Struct as StdlibStruct

from pants.engine.nodes import State
from pants.engine.objects import SerializationError


class Key(object):
  """Holds the digest for the object, which uniquely identifies it.

  The `_hash` is a memoized 32 bit integer hashcode computed from the digest.
  """

  __slots__ = ['_digest', '_hash']

  # The digest implementation used for Keys.
  _DIGEST_IMPL = sha1
  _DIGEST_SIZE = _DIGEST_IMPL().digest_size

  # A struct.Struct definition for grabbing the first 4 bytes off of a digest of
  # size DIGEST_SIZE, and discarding the rest.
  _32_BIT_STRUCT = StdlibStruct(b'<l' + (b'x' * (_DIGEST_SIZE - 4)))

  @classmethod
  def create(cls, blob):
    """Given a blob, hash it to construct a Key.

    :param blob: Binary content to hash.
    :param type_: Type of the object to be hashed.
    """
    return cls.create_from_digest(cls._DIGEST_IMPL(blob).digest())

  @classmethod
  def create_from_digest(cls, digest):
    """Given the digest for a key, create a Key.

    :param digest: The digest for the Key.
    """
    hash_ = cls._32_BIT_STRUCT.unpack(digest)[0]
    return cls(digest, hash_)

  def __init__(self, digest, hash_):
    """Not for direct use: construct a Key via `create` instead."""
    self._digest = digest
    self._hash = hash_

  @property
  def digest(self):
    return self._digest

  def __hash__(self):
    return self._hash

  def __eq__(self, other):
    return self._digest == other._digest

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return 'Key({})'.format(hexlify(self._digest))

  def __str__(self):
    return repr(self)


class InvalidKeyError(Exception):
  """Indicate an invalid `Key` entry"""


class Storage(object):
  """Stores and creates unique keys for input objects from their contents.

  This assumes objects can fit in memory, therefore there is no need to store their
  serialized form.

  Besides contents indexed by their hashed Keys, a secondary index is also provided
  for mappings between Keys. This allows to establish links between contents that
  are represented by those keys. Cache for example is such a use case.

  Convenience methods to translate nodes and states in
  `pants.engine.scheduler.StepRequest` and `pants.engine.scheduler.StepResult`
  into keys, and vice versa are also provided.
  """

  @classmethod
  def create(cls, protocol=None):
    """Create a content addressable Storage backed by a key value store.

    :param protocol: Serialization protocol for pickle, if not provided will use ASCII protocol.
    """
    return Storage(protocol=protocol)

  def __init__(self, protocol=None):
    """Not for direct use: construct a Storage via either `create` or `clone`."""
    self._objects = dict()
    self._key_mappings = dict()
    self._protocol = protocol if protocol is not None else pickle.HIGHEST_PROTOCOL

  def put(self, obj):
    """Serialize and hash something pickleable, returning a unique key to retrieve it later.

    NB: pickle by default memoizes objects by id and pickle repeated objects by references,
    for example, (A, A) uses less space than (A, A'), A and A' are equal but not identical.
    For content addressability we need equality. Use `fast` mode to turn off memo.
    Longer term see https://github.com/pantsbuild/pants/issues/2969
    """
    try:
      with closing(StringIO.StringIO()) as buf:
        pickler = pickle.Pickler(buf, protocol=self._protocol)
        pickler.fast = 1
        pickler.dump(obj)
        blob = buf.getvalue()

        # Hash the blob and store it if it does not exist.
        key = Key.create(blob)
        if key not in self._objects:
          self._objects[key] = obj
    except Exception as e:
      # Unfortunately, pickle can raise things other than PickleError instances.  For example it
      # will raise ValueError when handed a lambda; so we handle the otherwise overly-broad
      # `Exception` type here.
      raise SerializationError('Failed to pickle {}: {}'.format(obj, e), e)

    return key

  def get(self, key):
    """Given a key, return its deserialized content.

    Note that since this is not a cache, if we do not have the content for the object, this
    operation fails noisily.
    """
    if not isinstance(key, Key):
      raise InvalidKeyError('Not a valid key: {}'.format(key))

    return self._objects.get(key)

  def put_state(self, state):
    """Put the components of the State individually in storage, then put the aggregate."""
    return self.put(tuple(self.put(r).digest for r in state.to_components()))

  def get_state(self, state_key):
    """The inverse of put_state: get a State given its Key."""
    return State.from_components(tuple(self.get(Key.create_from_digest(d)) for d in self.get(state_key)))

  def add_mapping(self, from_key, to_key):
    """Establish one to one relationship from one Key to another Key.

    Content that keys represent should either already exist or the caller must
    check for existence.

    Unlike content storage, key mappings allows overwriting existing entries,
    meaning a key can be re-mapped to a different key.
    """
    if from_key.digest not in self._key_mappings:
      self._key_mappings[from_key.digest] = to_key

  def get_mapping(self, from_key):
    """Retrieve the mapping Key from a given Key.

    None is returned if the mapping does not exist.
    """
    return self._key_mappings.get(from_key.digest)


class Cache(object):
  """Cache the State resulting from a given Runnable."""

  @classmethod
  def create(cls, storage=None, cache_stats=None):
    """Create a Cache from a given storage instance."""

    storage = storage or Storage.create()
    cache_stats = cache_stats or CacheStats()
    return Cache(storage, cache_stats)

  def __init__(self, storage, cache_stats):
    """Initialize the cache. Not for direct use, use factory methods `create`.

    :param storage: Main storage for all requests and results.
    :param cache_stats: Stats for hits and misses.
    """
    self._storage = storage
    self._cache_stats = cache_stats

  def get(self, runnable):
    """Get the request key and hopefully a cached result for a given Runnable."""
    request_key = self._storage.put_state(runnable)
    return request_key, self.get_for_key(request_key)

  def get_for_key(self, request_key):
    """Given a request_key (for a Runnable), get the cached result."""
    result_key = self._storage.get_mapping(request_key)
    if result_key is None:
      self._cache_stats.add_miss()
      return None

    self._cache_stats.add_hit()
    return self._storage.get(result_key)

  def put(self, request_key, result):
    """Save the State for a given Runnable and return a key for the result."""
    result_key = self._storage.put(result)
    self.put_for_key(request_key, result_key)
    return result_key

  def put_for_key(self, request_key, result_key):
    """Save the State for a given Runnable and return a key for the result."""
    self._storage.add_mapping(from_key=request_key, to_key=result_key)

  def get_stats(self):
    return self._cache_stats

  def items(self):
    """Iterate over all cached request, result for testing purpose."""
    for digest, _ in self._storage._key_mappings.items():
      request_key = Key.create_from_digest(digest)
      request = self._storage.get(request_key)
      yield request, self._storage.get(self._storage.get_mapping(self._storage.put(request)))


class CacheStats(Counter):
  """Record cache hits and misses."""

  HIT_KEY = 'hits'
  MISS_KEY = 'misses'

  def add_hit(self):
    """Increment hit count by 1."""
    self[self.HIT_KEY] += 1

  def add_miss(self):
    """Increment miss count by 1."""
    self[self.MISS_KEY] += 1

  @property
  def hits(self):
    """Raw count for hits."""
    return self[self.HIT_KEY]

  @property
  def misses(self):
    """Raw count for misses."""
    return self[self.MISS_KEY]

  @property
  def total(self):
    """Total count including hits and misses."""
    return self[self.HIT_KEY] + self[self.MISS_KEY]

  def __repr__(self):
    return 'hits={}, misses={}, total={}'.format(self.hits, self.misses, self.total)
