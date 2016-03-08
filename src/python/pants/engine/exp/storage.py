# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import cPickle as pickle
import cStringIO
import sys
from abc import abstractmethod
from binascii import hexlify
from hashlib import sha1
from struct import Struct as StdlibStruct

import lmdb
import six

from pants.engine.exp.objects import Closable, SerializationError
from pants.util.dirutil import safe_mkdtemp
from pants.util.meta import AbstractClass


class Key(object):
  """Holds the digest for the object, which uniquely identifies it.

  The `_hash` is a memoized 32 bit integer hashcode computed from the digest.

  The `string` field holds the string representation of the object, but is optional (usually only
  used when debugging is enabled).

  NB: Because `string` is not included in equality comparisons, we cannot just use `datatype` here.
  """

  __slots__ = ['_digest', '_hash', '_string']

  # The digest implementation used for Keys.
  _DIGEST_IMPL = sha1
  _DIGEST_SIZE = _DIGEST_IMPL().digest_size

  # A struct.Struct definition for grabbing the first 4 bytes off of a digest of
  # size DIGEST_SIZE, and discarding the rest.
  _32_BIT_STRUCT = StdlibStruct(b'<l' + (b'x' * (_DIGEST_SIZE - 4)))

  @classmethod
  def create(cls, blob, string=None):
    """Given a blob, hash it to construct a Key.

    :param blob: Binary content to hash.
    :param string: An optional human-readable representation of the blob for debugging purposes.
    """
    digest = cls._DIGEST_IMPL(blob).digest()
    _hash = cls._32_BIT_STRUCT.unpack(digest)[0]
    return cls(digest, _hash, string)

  def __init__(self, digest, _hash, string):
    """Not for direct use: construct a Key via `create` instead."""
    self._digest = digest
    self._hash = _hash
    self._string = string

  @property
  def string(self):
    return self._string

  @property
  def digest(self):
    return self._digest

  def set_string(self, string):
    """Sets the string for a Key after construction.

    Since the string representation is not involved in `eq` or `hash`, this allows the key to be
    used for lookups before its string representation has been stored, and then only generated
    it the object will remain in use.
    """
    self._string = string

  def __hash__(self):
    return self._hash

  def __eq__(self, other):
    return type(other) == Key and self._digest == other._digest

  def __ne__(self, other):
    return not (self == other)

  def __repr__(self):
    return 'Key({}{})'.format(
        hexlify(self._digest),
        '' if self._string is None else ':[{}]'.format(self._string))

  def __str__(self):
    return repr(self)


class InvalidKeyError(Exception):
  """Indicate an invalid `Key` entry"""


class Storage(Closable):
  """Stores and creates unique keys for input Serializable objects.

  Storage as `Closable`, `close()` can be called either explicitly or through the `with`
  statement in a context.
  """

  @classmethod
  def create(cls, in_memory=False, debug=True, protocol=None):
    """Create a content addressable Storage backed by a key value store.

    :param in_memory: Indicate whether to use the in memory kvs or an embeded database.
    :param debug: A flag to store debug information in the key.
    :param protocol: Serialization protocol for pickle, if not provided will use ASCII protocol.
    """
    if in_memory:
      kvs = InMemoryDb()
    else:
      kvs = Lmdb()

    return Storage(kvs=kvs, debug=debug, protocol=protocol)

  @classmethod
  def clone(cls, storage):
    """Clone a Storage so it can be shared across process boundary."""
    if isinstance(storage._kvs, InMemoryDb):
      kvs = storage._kvs
    else:
      kvs = Lmdb(storage._kvs.path)

    return Storage(kvs=kvs, debug=storage._debug, protocol=storage._protocol)

  def __init__(self, kvs=None, debug=True, protocol=None):
    """Not for direct use: construct a Storage via either `create` or `clone`."""
    self._kvs = kvs
    self._debug = debug
    # TODO: Have seen strange inconsistencies with pickle protocol version 1/2 (ie, the
    # binary versions): in particular, bytes added into the middle of otherwise identical
    # objects.
    self._protocol = protocol if protocol is not None else 0

  def put(self, obj):
    """Serialize and hash a Serializable, returning a unique key to retrieve it later."""
    try:
      blob = pickle.dumps(obj, protocol=self._protocol)
    except Exception as e:
      # Unfortunately, pickle can raise things other than PickleError instances.  For example it
      # will raise ValueError when handed a lambda; so we handle the otherwise overly-broad
      # `Exception` type here.
      raise SerializationError('Failed to pickle {}: {}'.format(obj, e))

    # Hash the blob and store it if it does not exist.
    if self._debug:
      key = Key.create(blob, str(obj))
    else:
      key = Key.create(blob)

    self._kvs.put(key.digest, blob)
    return key

  def get(self, key):
    """Given a key, return its deserialized content.

    Note that since this is not a cache, if we do not have the content for the object, this
    operation fails noisily.
    """
    if not isinstance(key, Key):
      raise InvalidKeyError('Not a valid key: {}'.format(key))

    value = self._kvs.get(key.digest)
    if isinstance(value, six.binary_type):
      # loads for string-like values
      return pickle.loads(value)
    # load for file-like value from buffers
    return pickle.load(value)

  def close(self):
    self._kvs.close()


class KeyValueStore(Closable, AbstractClass):
  @abstractmethod
  def get(self, key):
    """Fetch the value for a given key.

    :param key: key in bytestring.
    :return: value can be either string-like or file-like, `None` if does not exist.
    """

  @abstractmethod
  def put(self, key, value):
    """Save the value under a key, but only once.

    The write once semantics is specifically provided for the content addressable use case.

    :param key: key in bytestring.
    :param value: value in bytestring.
    :return: `True` to indicate the write actually happens, i.e, first write, `False` for
      repeated writes of the same key.
    """


class InMemoryDb(KeyValueStore):
  """An in-memory implementation of the kvs interface."""

  def __init__(self):
    self._storage = dict()

  def get(self, key):
    return self._storage.get(key)

  def put(self, key, value):
    if key in self._storage:
      return False
    self._storage[key] = value
    return True


class Lmdb(KeyValueStore):
  """A lmdb implementation of the kvs interface."""

  # TODO make this more configurable through a subsystem.

  # 256MB - some arbitrary maximum size database may grow to. Theoretical upper bound
  # is the entire memory address space, i.e, 2^32 or 2^64.
  MAX_DATABASE_SIZE = 256 * 1024 * 1024

  # writemap will use a writeable memory mapping to directly update storage, therefore
  # improves performance. But it may cause filesystems that don’t support sparse files,
  # such as OSX, to immediately preallocate map_size = bytes of underlying storage.
  # See https://lmdb.readthedocs.org/en/release/#writemap-mode
  USE_SPARSE_FILES = sys.platform != 'darwin'

  def __init__(self, path=None):
    """Initialize the database.

    :param path: database directory location, if `None` a temporary location will be provided
      and cleaned up upon process exit.
    """
    self._path = path or safe_mkdtemp()
    self._env = lmdb.open(self._path, map_size=self.MAX_DATABASE_SIZE,
                          metasync=False, sync=False, map_async=True,
                          writemap=self.USE_SPARSE_FILES)

  @property
  def path(self):
    return self._path

  def get(self, key):
    """Return the value or `None` if the key does not exist.

    NB: Memory mapped storage returns a buffer object without copying keys or values, which
    is then wrapped with `StringIO` as the more friendly string buffer to allow `pickle.load`
    to read, again no copy involved.
    """
    with self._env.begin(buffers=True) as txn:
      value = txn.get(key)
      if value is not None:
        return cStringIO.StringIO(value)
      return None

  def put(self, key, value):
    """Returning True if the key/value are actually written to the storage."""
    with self._env.begin(buffers=True, write=True) as txn:
      return txn.put(key, value, overwrite=False)

  def close(self):
    """Close the lmdb environment, calling multiple times has no effect."""
    self._env.close()
