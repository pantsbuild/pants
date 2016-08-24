# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from cffi import FFI

from pants.binaries.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem


_FFI = FFI()
_FFI.cdef(
    '''
    typedef struct {
      char digest[32];
    } Digest;

    typedef Digest TypeId;
    typedef Digest Function;

    typedef struct {
      Digest   digest;
      TypeId   type_id;
    } Key;

    typedef struct {
      char*    str_ptr;
      uint64_t str_len;
      uint64_t str_cap;
    } UTF8Buffer;

    typedef struct {
      Key*     keys_ptr;
      uint64_t keys_len;
      uint64_t keys_cap;
    } KeyBuffer;

    typedef uint64_t EntryId;
    typedef Key Field;

    typedef void StorageHandle;

    typedef UTF8Buffer* (*extern_to_str)(StorageHandle*, Digest*);
    typedef bool        (*extern_isinstance)(StorageHandle*, Key*, TypeId*);
    typedef Key         (*extern_store_list)(StorageHandle*, Key*, uint64_t);
    typedef Key         (*extern_project)(StorageHandle*, Key*, Field*, TypeId*);
    typedef KeyBuffer*  (*extern_project_multi)(StorageHandle*, Key*, Field*);

    typedef struct {
      Function*   func;
      Key*        args_ptr;
      uint64_t    args_len;
      bool        cacheable;
    } RawRunnable;

    typedef struct {
      Key*        func;
      Key*        args_ptr;
      uint64_t    args_len;
    } Complete;

    typedef struct {
      EntryId*              ready_ptr;
      RawRunnable*          ready_runnables_ptr;
      uint64_t              ready_len;
      // NB: there are more fields in this struct, but we can safely (?)
      // ignore them because we never have collections of this type.
    } RawExecution;

    typedef struct {
      RawExecution execution;
      // NB: there are more fields in this struct, but we can safely (?)
      // ignore them because we never have collections of this type.
    } RawScheduler;

    typedef enum {
      Empty = 0,
      Return = 1,
      Throw = 2,
      Noop = 3,
    } RawState;

    typedef struct {
      Key      subject;
      TypeId   product;
      uint8_t  union_tag;
      Key      union_return;
      bool     union_throw;
      bool     union_noop;
    } RawNode;

    typedef struct {
      RawNode*  nodes_ptr;
      uint64_t  nodes_len;
      // NB: there are more fields in this struct, but we can safely (?)
      // ignore them because we never have collections of this type.
    } RawNodes;

    RawScheduler* scheduler_create(StorageHandle*,
                                   extern_to_str,
                                   extern_isinstance,
                                   extern_store_list,
                                   extern_project,
                                   extern_project_multi,
                                   Field,
                                   Field,
                                   Field,
                                   TypeId,
                                   TypeId,
                                   TypeId);
    void scheduler_destroy(RawScheduler*);

    void intrinsic_task_add(RawScheduler*, Function, TypeId, TypeId);

    void task_add(RawScheduler*, Function, TypeId);
    void task_add_select(RawScheduler*, TypeId);
    void task_add_select_variant(RawScheduler*, TypeId, Key);
    void task_add_select_literal(RawScheduler*, Key, TypeId);
    void task_add_select_dependencies(RawScheduler*, TypeId, TypeId, Field);
    void task_add_select_projection(RawScheduler*, TypeId, TypeId, Field, TypeId);
    void task_end(RawScheduler*);

    uint64_t graph_len(RawScheduler*);
    void graph_visualize(RawScheduler*, char*);

    void execution_reset(RawScheduler*);
    void execution_add_root_select(RawScheduler*, Key, TypeId);
    void execution_add_root_select_dependencies(RawScheduler*,
                                                Key,
                                                TypeId,
                                                TypeId,
                                                Field);
    void execution_next(RawScheduler*,
                        EntryId*,
                        Key*,
                        uint64_t,
                        EntryId*,
                        uint64_t);
    RawNodes* execution_roots(RawScheduler*);

    void nodes_destroy(RawNodes*);
    '''
  )


# Static buffers used for all extern calls. Not threadsafe.
# TODO: All of these functions need (better) error handling.
_UTF8_BUF = _FFI.new('UTF8Buffer*', (_FFI.new('char[]', 256), 256, 256))
_KEYS_BUF = _FFI.new('KeyBuffer*', (_FFI.new('Key[]', 64), 64, 64))


@_FFI.callback("UTF8Buffer*(StorageHandle*, Digest*)")
def extern_to_str(storage_handle, digest):
  """Given storage and a Digest for `obj`, write str(obj) and return it."""
  storage = _FFI.from_handle(storage_handle)
  obj = storage.get_from_digest(_FFI.buffer(digest.digest)[:])
  str_bytes = str(obj).encode('utf-8')
  if _UTF8_BUF.str_cap < len(str_bytes):
    new_cap = max(len(str_bytes), _UTF8_BUF.str_cap * 2)
    _UTF8_BUF.str_ptr = _FFI.new('char[]', new_cap)
    _UTF8_BUF.str_cap = new_cap
  _UTF8_BUF.str_ptr[0:len(str_bytes)] = str_bytes
  _UTF8_BUF.str_len = len(str_bytes)
  return _UTF8_BUF


@_FFI.callback("bool(StorageHandle*, Key*, TypeId*)")
def extern_isinstance(storage_handle, key, type_id):
  """Given storage, a Key for `obj`, and a TypeId for `type`, return isinstance(obj, type)."""
  storage = _FFI.from_handle(storage_handle)
  obj = storage.get_from_digest(_FFI.buffer(key.digest.digest)[:])
  typ = storage.get_from_digest(_FFI.buffer(type_id.digest)[:])
  print(">>> extern_isinstance({}, {}) == {}".format(obj, typ, isinstance(obj, typ)))
  return isinstance(obj, typ)


@_FFI.callback("Key(StorageHandle*, Key*, uint64_t)")
def extern_store_list(storage_handle, keys_ptr, keys_len):
  """Given storage and an array of Keys, return a new Key to represent the list."""
  storage = _FFI.from_handle(storage_handle)
  digests = [_FFI.buffer(key.digest.digest)[:] for key in _FFI.unpack(keys_ptr, keys_len)]
  key = storage.put_from_digests(digests)
  print(">>> extern_store_list({}) == {}".format(len(digests), key))
  # NB: not actually storing the digest of the type of KeyList here, since it is not
  # supposed to be an exposed type. This effectively means that it is a "unique" type.
  return ((key.digest,), (key.digest,))


@_FFI.callback("Key(StorageHandle*, Key*, Field*, TypeId*)")
def extern_project(storage_handle, key, field, type_id):
  """Given storage, a Key for `obj`, a field name, and a type, project the field as a new Key."""
  storage = _FFI.from_handle(storage_handle)
  obj = storage.get_from_digest(_FFI.buffer(key.digest.digest)[:])
  field_name = storage.get_from_digest(_FFI.buffer(field.digest.digest)[:])
  typ = storage.get_from_digest(_FFI.buffer(type_id.digest)[:])

  projected = getattr(obj, field_name)
  if type(projected) is not typ:
    projected = typ(projected)

  return ((storage.put(projected).digest,), (storage.put(type(projected)).digest,))


@_FFI.callback("KeyBuffer*(StorageHandle*, Key*, Field*)")
def extern_project_multi(storage_handle, key, field):
  """Given storage, a Key for `obj`, and a field name, project the field as a list of Keys."""
  storage = _FFI.from_handle(storage_handle)
  obj = storage.get_from_digest(_FFI.buffer(key.digest.digest)[:])
  field_name = storage.get_from_digest(_FFI.buffer(field.digest.digest)[:])

  projected = [((storage.put(p).digest,), (storage.put(type(p)).digest,))
               for p in getattr(obj, field_name)]
  if _KEYS_BUF.keys_cap < len(projected):
    new_cap = max(len(projected), _KEYS_BUF.keys_cap * 2)
    _KEYS_BUF.keys_ptr = _FFI.new('Key[]', new_cap)
    _KEYS_BUF.keys_cap = new_cap
  _KEYS_BUF.keys_ptr[0:len(projected)] = projected
  _KEYS_BUF.keys_len = len(projected)
  return _KEYS_BUF


class Native(object):
  """Encapsulates fetching a platform specific version of the native portion of the engine.
  """

  class Factory(Subsystem):
    options_scope = 'native-engine'

    @classmethod
    def subsystem_dependencies(cls):
      return (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      register('--version', advanced=True, default='0.0.1',
               help='Native engine version.')
      register('--supportdir', advanced=True, default='dylib/native-engine',
               help='Find native engine binaries under this dir. Used as part of the path to lookup '
                    'the binary with --binary-util-baseurls and --pants-bootstrapdir.')

    def create(self):
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return Native(binary_util, options.version, options.supportdir)

  def __init__(self, binary_util, version, supportdir):
    """
    :param binary_util: The BinaryUtil subsystem instance for binary retrieval.
    :param version: The binary version of the native engine.
    :param supportdir: The supportdir for the native engine.
    """
    self._binary_util = binary_util
    self._version = version
    self._supportdir = supportdir

    self._lib_field = None

  @property
  def lib(self):
    """Load and return the `libgraph` module."""
    if self._lib_field is None:
      binary = self._binary_util.select_binary(self._supportdir,
                                              self._version,
                                              'native-engine')
      self._lib_field = _FFI.dlopen(binary)
    return self._lib_field

  def new(self, cdecl, init):
    return _FFI.new(cdecl, init)

  def gc(self, cdata, destructor):
    """Register a method to be called when `cdata` is garbage collected.

    Returns a new reference that should be used in place of `cdata`.
    """
    return _FFI.gc(cdata, destructor)

  def unpack(self, cdata_ptr, count):
    """Given a pointer representing an array, and its count of entries, return a list."""
    return _FFI.unpack(cdata_ptr, count)

  def new_handle(self, obj):
    return _FFI.new_handle(obj)

  def from_handle(self, handle):
    return _FFI.from_handle(handle)

  def buffer(self, cdata):
    return _FFI.buffer(cdata)
