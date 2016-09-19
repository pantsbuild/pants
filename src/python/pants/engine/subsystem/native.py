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
    } UTF8Buffer;

    typedef struct {
      Key*     keys_ptr;
      uint64_t keys_len;
    } KeyBuffer;

    typedef uint64_t EntryId;
    typedef Key Field;

    typedef void ExternContext;

    typedef UTF8Buffer  (*extern_to_str)(ExternContext*, Digest*);
    typedef bool        (*extern_issubclass)(ExternContext*, TypeId*, TypeId*);
    typedef Key         (*extern_store_list)(ExternContext*, Key*, uint64_t, bool);
    typedef Key         (*extern_project)(ExternContext*, Key*, Field*, TypeId*);
    typedef KeyBuffer   (*extern_project_multi)(ExternContext*, Key*, Field*);

    typedef struct {
      uint8_t  tag;
      Key      key;
      EntryId  promise;
    } RawArg;

    typedef struct {
      EntryId     id;
      Function*   func;
      RawArg*     args_ptr;
      uint64_t    args_len;
      bool        cacheable;
    } RawRunnable;

    typedef struct {
      Key*        func;
      Key*        args_ptr;
      uint64_t    args_len;
    } Complete;

    typedef struct {
      RawRunnable*          runnables_ptr;
      uint64_t              runnables_len;
      // NB: there are more fields in this struct, but we can safely (?)
      // ignore them because we never have collections of this type.
    } RawExecution;

    typedef struct {
      RawExecution execution;
      // NB: there are more fields in this struct, but we can safely (?)
      // ignore them because we never have collections of this type.
    } RawScheduler;

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

    RawScheduler* scheduler_create(ExternContext*,
                                   extern_to_str,
                                   extern_issubclass,
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
    void task_add_select_dependencies(RawScheduler*, TypeId, TypeId, Field, bool);
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
                                                Field,
                                                bool);
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


@_FFI.callback("UTF8Buffer(ExternContext*, Digest*)")
def extern_to_str(context_handle, digest):
  """Given storage and a Digest for `obj`, write str(obj) and return it."""
  c = _FFI.from_handle(context_handle)
  obj = c.storage.get_from_digest(_FFI.buffer(digest.digest)[:])
  str_bytes = str(obj).encode('utf-8')
  return (c.utf8_buf(str_bytes), len(str_bytes))


@_FFI.callback("bool(ExternContext*, TypeId*, TypeId*)")
def extern_issubclass(context_handle, cls_id, super_cls_id):
  """Given storage and two TypeIds, return issubclass(left, right)."""
  c = _FFI.from_handle(context_handle)
  cls = c.storage.get_from_digest(_FFI.buffer(cls_id.digest)[:])
  super_cls = c.storage.get_from_digest(_FFI.buffer(super_cls_id.digest)[:])
  return issubclass(cls, super_cls)


@_FFI.callback("Key(ExternContext*, Key*, uint64_t, bool)")
def extern_store_list(context_handle, keys_ptr, keys_len, concat):
  """Given storage and an array of Keys, return a new Key to represent the list."""
  c = _FFI.from_handle(context_handle)
  digests = [_FFI.buffer(key.digest.digest)[:] for key in _FFI.unpack(keys_ptr, keys_len)]
  if concat:
    # Expect each digest to represent a list: deserialize without nesting to get a list
    # of inner digests per outer digest, and concatenate.
    digests = tuple(inner
                    for digest in digests
                    for inner in c.storage.get_from_digest(digest, nesting=False))
  return c.storage.put_typed_from_digests(digests)


@_FFI.callback("Key(ExternContext*, Key*, Field*, TypeId*)")
def extern_project(context_handle, key, field, type_id):
  """Given storage, a Key for `obj`, a field name, and a type, project the field as a new Key."""
  c = _FFI.from_handle(context_handle)
  obj = c.storage.get_from_digest(_FFI.buffer(key.digest.digest)[:])
  field_name = c.storage.get_from_digest(_FFI.buffer(field.digest.digest)[:])
  typ = c.storage.get_from_digest(_FFI.buffer(type_id.digest)[:])

  projected = getattr(obj, field_name)
  if type(projected) is not typ:
    projected = typ(projected)

  return c.storage.put_typed(projected)


@_FFI.callback("KeyBuffer(ExternContext*, Key*, Field*)")
def extern_project_multi(context_handle, key, field):
  """Given storage, a Key for `obj`, and a field name, project the field as a list of Keys."""
  c = _FFI.from_handle(context_handle)
  obj = c.storage.get_from_digest(_FFI.buffer(key.digest.digest)[:])
  field_name = c.storage.get_from_digest(_FFI.buffer(field.digest.digest)[:])

  projected = [c.storage.put_typed(p) for p in getattr(obj, field_name)]
  return (c.keys_buf(projected), len(projected))


class ExternContext(object):
  """A wrapper around python objects used in static extern functions in this module."""

  def __init__(self, storage):
    self._storage = storage
    self._resize_utf8(256)
    self._resize_keys(64)

  def _resize_utf8(self, size):
    self._utf8_cap = size
    self._utf8_buf = _FFI.new('char[]', self._utf8_cap)

  def _resize_keys(self, size):
    self._keys_cap = size
    self._keys_buf = _FFI.new('Key[]', self._keys_cap)

  @property
  def storage(self):
    return self._storage

  def utf8_buf(self, utf8):
    if self._utf8_cap < len(utf8):
      self._resize_utf8(max(len(utf8), 2 * self._utf8_cap))
    self._utf8_buf[0:len(utf8)] = utf8
    return self._utf8_buf

  def keys_buf(self, keys):
    if self._keys_cap < len(keys):
      self._resize_keys(max(len(keys), 2 * self._keys_cap))
    self._keys_buf[0:len(keys)] = keys
    return self._keys_buf


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

  def buffer(self, cdata):
    return _FFI.buffer(cdata)
