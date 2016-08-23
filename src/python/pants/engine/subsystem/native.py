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

    typedef struct {
      char buf[255];
    } FixedBuffer;

    typedef Digest TypeId;
    typedef Digest Function;

    typedef struct {
      Digest   digest;
      TypeId   type_id;
    } Key;

    typedef uint64_t EntryId;
    typedef Key Field;

    typedef void StorageHandle;

    typedef uint8_t (*extern_to_str)(StorageHandle*, Digest*, FixedBuffer*);
    typedef bool    (*extern_isinstance)(StorageHandle*, Key*, TypeId*);
    typedef Key     (*extern_store_list)(StorageHandle*, Key*, uint64_t);

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


@_FFI.callback("uint8_t(StorageHandle*, Digest*, FixedBuffer*)")
def extern_to_str(storage_handle, digest, output_buffer):
  """Given storage, a Digest for `obj`, and a buffer to write to, write str(obj) and return a length."""
  storage = _FFI.from_handle(storage_handle)
  obj = storage.get_from_digest(_FFI.buffer(digest.digest)[:])
  str_bytes = str(obj).encode('utf-8')
  output = _FFI.buffer(output_buffer.buf)
  write_len = min(len(str_bytes), len(output))
  output[0:write_len] = str_bytes[0:write_len]
  return write_len


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
  """Given storage, a Key for `obj`, and a TypeId for `type`, return isinstance(obj, type)."""
  storage = _FFI.from_handle(storage_handle)
  digests = [_FFI.buffer(key.digest.digest)[:] for key in _FFI.unpack(keys_ptr, keys_len)]
  key = storage.put_from_digests(digests)
  print(">>> extern_store_list({}) == {}".format(len(digests), key))
  # NB: not actually storing the digest of the type of KeyList here, since it is not
  # supposed to be an exposed type. This effectively means that it is a "unique" type.
  return ((key.digest,), (key.digest,))


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
