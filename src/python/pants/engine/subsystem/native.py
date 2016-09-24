# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from cffi import FFI

from pants.binaries.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem
from pants.util.objects import datatype


_FFI = FFI()
_FFI.cdef(
    '''
    typedef struct {
      uint64_t key;
    } Id;

    typedef Id TypeId;
    typedef Id Function;

    typedef struct {
      Id       key;
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

    typedef UTF8Buffer  (*extern_to_str)(ExternContext*, Id*);
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


@_FFI.callback("UTF8Buffer(ExternContext*, Id*)")
def extern_to_str(context_handle, _id):
  """Given an Id for `obj`, write str(obj) and return it."""
  c = _FFI.from_handle(context_handle)
  obj = c.from_id(_id)
  str_bytes = str(obj).encode('utf-8')
  return (c.utf8_buf(str_bytes), len(str_bytes))


@_FFI.callback("bool(ExternContext*, TypeId*, TypeId*)")
def extern_issubclass(context_handle, cls_id, super_cls_id):
  """Given two TypeIds, return issubclass(cls, super_cls)."""
  c = _FFI.from_handle(context_handle)
  return issubclass(c.from_id(cls_id), c.from_id(super_cls_id))


@_FFI.callback("Key(ExternContext*, Key*, uint64_t, bool)")
def extern_store_list(context_handle, keys_ptr, keys_len, merge):
  """Given storage and an array of Keys, return a new Key to represent the list."""
  c = _FFI.from_handle(context_handle)
  keys = tuple(c.key_from_native(key).key for key in _FFI.unpack(keys_ptr, keys_len))
  if merge:
    # Expect each Id to represent a list: deserialize without nesting to get a list
    # of inner Ids per outer Id, then merge.
    merged = {key
              for outer_key in keys
              for key in c.get(outer_key, nesting=False)}
    keys = tuple(merged)
  return c.to_key(keys, nesting=False)


@_FFI.callback("Key(ExternContext*, Key*, Field*, TypeId*)")
def extern_project(context_handle, key, field, type_id):
  """Given a Key for `obj`, a field name, and a type, project the field as a new Key."""
  c = _FFI.from_handle(context_handle)
  obj = c.from_key(key)
  field_name = c.from_key(field)
  typ = c.from_id(type_id)

  projected = getattr(obj, field_name)
  if type(projected) is not typ:
    projected = typ(projected)

  return c.to_key(projected)


@_FFI.callback("KeyBuffer(ExternContext*, Key*, Field*)")
def extern_project_multi(context_handle, key, field):
  """Given a Key for `obj`, and a field name, project the field as a list of Keys."""
  c = _FFI.from_handle(context_handle)
  obj = c.from_key(key)
  field_name = c.from_key(field)

  projected = [c.to_key(p) for p in getattr(obj, field_name)]
  return (c.keys_buf(projected), len(projected))


class Key(datatype('Key', ['key', 'type_id'])):
  """Corresponds to the native object of the same name, and holds two Id objects."""


class Id(datatype('Id', ['value'])):
  """Corresponds to the native object of the same name."""


class ExternContext(object):
  """A wrapper around python objects used in static extern functions in this module.
  
  In the native context, python objects are identified by an unsigned-integer Id which is
  assigned and memoized here. Note that this is independent-from and much-lighter-than
  the Digest computed when an object is stored via storage.py (which is generally only necessary
  for multi-processing or cache lookups).
  """

  def __init__(self):
    # NB: These two dictionaries are not always the same size, because un-hashable objects will
    # not be memoized in `_obj_to_id`, but will still have unique ids assigned in `_id_to_obj`.
    # TODO: disallow non-hashable objects.
    self._obj_to_id = dict()
    self._id_to_obj = dict()
    self._id_generator = 0

    # Buffers for transferring strings and arrays of Keys.
    self._resize_utf8(256)
    self._resize_keys(64)
 
  def _resize_utf8(self, size):
    self._utf8_cap = size
    self._utf8_buf = _FFI.new('char[]', self._utf8_cap)

  def _resize_keys(self, size):
    self._keys_cap = size
    self._keys_buf = _FFI.new('Key[]', self._keys_cap)

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

  def key_from_native(self, cdata):
    return Key(self._id_from_native(cdata.key), self._id_from_native(cdata.type_id))

  def _id_from_native(self, cdata):
    return Id(cdata.key)

  def _maybe_put_nested(self, obj):
    # If the stored object is a collection type, recurse.
    if type(obj) in (tuple, list):
      return type(obj)(self.put(inner) for inner in obj)
    else:
      return obj

  def _maybe_get_nested(self, obj):
    # If the stored object was a collection type, recurse.
    if type(obj) in (tuple, list):
      return type(obj)(self.get(inner) for inner in obj)
    else:
      return obj

  def put(self, obj, nesting=True):
    obj = self._maybe_put_nested(obj) if nesting else obj

    # Attempt to memoize the object, and if we encounter an existing id, return it.
    new_id = Id(self._id_generator)
    try:
      _id = self._obj_to_id.setdefault(obj, new_id)
      if _id is not new_id:
        # Object already existed.
        return _id
      # Object was newly stored.
    except TypeError:
      # Object was not hashable.
      _id = new_id

    # Object is new/unique.
    self._id_to_obj[_id] = obj
    self._id_generator += 1
    return _id

  def get(self, _id, nesting=True):
    obj = self._id_to_obj[_id]
    return self._maybe_get_nested(obj) if nesting else obj

  def to_id(self, typ):
    return self.put(typ)

  def to_key(self, obj, nesting=True):
    return Key(self.put(obj, nesting=nesting), self.put(type(obj)))

  def from_id(self, cdata, nesting=True):
    return self.get(self._id_from_native(cdata), nesting=nesting)

  def from_key(self, cdata):
    return self.get(self._id_from_native(cdata.key))


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
