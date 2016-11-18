# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pkg_resources
from cffi import FFI
from twitter.common.collections import OrderedSet

from pants.binaries.binary_util import BinaryUtil
from pants.option.custom_types import dir_option
from pants.subsystem.subsystem import Subsystem
from pants.util.objects import datatype


_FFI = FFI()
_FFI.cdef(
    '''
    typedef uint64_t Id;

    typedef struct {
      Id id_;
    } TypeId;

    typedef struct {
      Id id_;
    } TypeConstraint;

    typedef struct {
      Id id_;
    } Function;

    typedef struct {
      void*    handle;
      TypeId   type_id;
    } Value;

    typedef struct {
      Id       id_;
      Value    value;
      TypeId   type_id;
    } Key;

    typedef Key Field;

    typedef struct {
      char*    str_ptr;
      uint64_t str_len;
    } UTF8Buffer;

    typedef struct {
      Value*     values_ptr;
      uint64_t   values_len;
    } ValueBuffer;

    typedef uint64_t EntryId;

    typedef void ExternContext;

    typedef Key         (*extern_key_for)(ExternContext*, Value*);
    typedef UTF8Buffer  (*extern_id_to_str)(ExternContext*, Id);
    typedef UTF8Buffer  (*extern_val_to_str)(ExternContext*, Value*);
    typedef bool        (*extern_satisfied_by)(ExternContext*, TypeConstraint*, TypeId*);
    typedef Value       (*extern_store_list)(ExternContext*, Value*, uint64_t, bool);
    typedef Value       (*extern_project)(ExternContext*, Value*, Field*, TypeId*);
    typedef ValueBuffer (*extern_project_multi)(ExternContext*, Value*, Field*);

    typedef struct {
      EntryId     id;
      Function*   func;
      Value*      args_ptr;
      uint64_t    args_len;
      bool        cacheable;
    } RawRunnable;

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
      Key             subject;
      TypeConstraint  product;
      uint8_t         union_tag;
      Value           union_return;
      bool            union_throw;
      bool            union_noop;
    } RawNode;

    typedef struct {
      RawNode*  nodes_ptr;
      uint64_t  nodes_len;
      // NB: there are more fields in this struct, but we can safely (?)
      // ignore them because we never have collections of this type.
    } RawNodes;

    RawScheduler* scheduler_create(ExternContext*,
                                   extern_key_for,
                                   extern_id_to_str,
                                   extern_val_to_str,
                                   extern_satisfied_by,
                                   extern_store_list,
                                   extern_project,
                                   extern_project_multi,
                                   Field,
                                   Field,
                                   Field,
                                   TypeConstraint,
                                   TypeConstraint,
                                   TypeConstraint);
    void scheduler_destroy(RawScheduler*);

    void intrinsic_task_add(RawScheduler*, Function, TypeId, TypeConstraint, TypeConstraint);
    void singleton_task_add(RawScheduler*, Function, TypeConstraint);

    void task_add(RawScheduler*, Function, TypeConstraint);
    void task_add_select(RawScheduler*, TypeConstraint);
    void task_add_select_variant(RawScheduler*, TypeConstraint, UTF8Buffer);
    void task_add_select_literal(RawScheduler*, Key, TypeConstraint);
    void task_add_select_dependencies(RawScheduler*, TypeConstraint, TypeConstraint, Field, bool);
    void task_add_select_projection(RawScheduler*, TypeConstraint, TypeConstraint, Field, TypeConstraint);
    void task_end(RawScheduler*);

    uint64_t graph_len(RawScheduler*);
    uint64_t graph_invalidate(RawScheduler*, Key*, uint64_t);
    void graph_visualize(RawScheduler*, char*);
    char* graph_trace(RawScheduler*);
    void string_destroy(char*);


    void execution_reset(RawScheduler*);
    void execution_add_root_select(RawScheduler*, Key, TypeConstraint);
    void execution_add_root_select_dependencies(RawScheduler*,
                                                Key,
                                                TypeConstraint,
                                                TypeConstraint,
                                                Field,
                                                bool);
    void execution_next(RawScheduler*,
                        EntryId*,
                        Value*,
                        uint64_t,
                        EntryId*,
                        uint64_t);
    RawNodes* execution_roots(RawScheduler*);

    void nodes_destroy(RawNodes*);
    '''
  )


@_FFI.callback("Key(ExternContext*, Value*)")
def extern_key_for(context_handle, val):
  """Return a Key for a Value."""
  c = _FFI.from_handle(context_handle)
  return c.value_to_key(val)


@_FFI.callback("UTF8Buffer(ExternContext*, Id)")
def extern_id_to_str(context_handle, id_):
  """Given an Id for `obj`, write str(obj) and return it."""
  c = _FFI.from_handle(context_handle)
  return c.utf8_buf(str(c.from_id(id_)))


@_FFI.callback("UTF8Buffer(ExternContext*, Value*)")
def extern_val_to_str(context_handle, val):
  """Given a Value for `obj`, write str(obj) and return it."""
  c = _FFI.from_handle(context_handle)
  return c.utf8_buf(str(c.from_value(val)))


@_FFI.callback("bool(ExternContext*, TypeConstraint*, TypeId*)")
def extern_satisfied_by(context_handle, constraint_id, cls_id):
  """Given two TypeIds, return constraint.satisfied_by(cls)."""
  c = _FFI.from_handle(context_handle)
  return c.from_id(constraint_id.id_).satisfied_by_type(c.from_id(cls_id.id_))


@_FFI.callback("Value(ExternContext*, Value*, uint64_t, bool)")
def extern_store_list(context_handle, vals_ptr, vals_len, merge):
  """Given storage and an array of Values, return a new Value to represent the list."""
  c = _FFI.from_handle(context_handle)
  vals = tuple(c.from_value(val) for val in _FFI.unpack(vals_ptr, vals_len))
  if merge:
    # Expect each obj to represent a list, and do a de-duping merge.
    merged = OrderedSet()
    for outer_val in vals:
      merged.update(outer_val)
    vals = tuple(merged)
  return c.to_value(vals)


@_FFI.callback("Value(ExternContext*, Value*, Field*, TypeId*)")
def extern_project(context_handle, val, field, type_id):
  """Given a Key for `obj`, a field name, and a type, project the field as a new Key."""
  c = _FFI.from_handle(context_handle)
  obj = c.from_value(val)
  field_name = c.from_key(field)
  typ = c.from_id(type_id.id_)

  projected = getattr(obj, field_name)
  if type(projected) is not typ:
    projected = typ(projected)

  return c.to_value(projected)


@_FFI.callback("ValueBuffer(ExternContext*, Value*, Field*)")
def extern_project_multi(context_handle, val, field):
  """Given a Key for `obj`, and a field name, project the field as a list of Keys."""
  c = _FFI.from_handle(context_handle)
  obj = c.from_value(val)
  field_name = c.from_key(field)

  projected = tuple(c.to_value(p) for p in getattr(obj, field_name))
  return (c.vals_buf(projected), len(projected))


class Value(datatype('Value', ['handle', 'type_id'])):
  """Corresponds to the native object of the same name."""


class Key(datatype('Key', ['id_', 'value', 'type_id'])):
  """Corresponds to the native object of the same name."""


class Function(datatype('Function', ['id_'])):
  """Corresponds to the native object of the same name."""


class TypeConstraint(datatype('TypeConstraint', ['id_'])):
  """Corresponds to the native object of the same name."""


class TypeId(datatype('TypeId', ['id_'])):
  """Corresponds to the native object of the same name."""


class ExternContext(object):
  """A wrapper around python objects used in static extern functions in this module.

  In the native context, python objects are identified by an unsigned-integer Id which is
  assigned and memoized here. Note that this is independent-from and much-lighter-than
  the Digest computed when an object is stored via storage.py (which is generally only necessary
  for multi-processing or cache lookups).
  """

  def __init__(self):
    # Memoized object Ids.
    self._id_generator = 0
    self._id_to_obj = dict()
    self._obj_to_id = dict()

    # Outstanding FFI object handles.
    self._handles = set()

    # Buffers for transferring strings and arrays of Keys.
    self._resize_utf8(256)
    self._resize_keys(64)

  def _resize_utf8(self, size):
    self._utf8_cap = size
    self._utf8_buf = _FFI.new('char[]', self._utf8_cap)

  def _resize_keys(self, size):
    self._keys_cap = size
    self._vals_buf = _FFI.new('Value[]', self._keys_cap)

  def utf8_buf(self, string):
    utf8 = string.encode('utf-8')
    if self._utf8_cap < len(utf8):
      self._resize_utf8(max(len(utf8), 2 * self._utf8_cap))
    self._utf8_buf[0:len(utf8)] = utf8
    return (self._utf8_buf, len(utf8))

  def vals_buf(self, keys):
    if self._keys_cap < len(keys):
      self._resize_keys(max(len(keys), 2 * self._keys_cap))
    self._vals_buf[0:len(keys)] = keys
    return self._vals_buf

  def to_value(self, obj, type_id=None):
    handle = _FFI.new_handle(obj)
    self._handles.add(handle)
    type_id = type_id or TypeId(self.to_id(type(obj)))
    return Value(handle, type_id)

  def from_value(self, val):
    return _FFI.from_handle(val.handle)

  def key_from_native(self, cdata):
    return Key(cdata.key, TypeId(cdata.type_id.id_))

  def _type_id_from_native(self, cdata):
    return TypeId(cdata.key)

  def put(self, obj):
    # If we encounter an existing id, return it.
    new_id = self._id_generator
    _id = self._obj_to_id.setdefault(obj, new_id)
    if _id is not new_id:
      # Object already existed.
      return _id

    # Object is new/unique.
    self._id_to_obj[_id] = obj
    self._id_generator += 1
    return _id

  def get(self, id_):
    return self._id_to_obj[id_]

  def to_id(self, typ):
    return self.put(typ)

  def value_to_key(self, val):
    obj = self.from_value(val)
    type_id = TypeId(val.type_id.id_)
    return Key(self.put(obj), Value(val.handle, type_id), type_id)

  def to_key(self, obj):
    type_id = TypeId(self.put(type(obj)))
    return Key(self.put(obj), self.to_value(obj, type_id=type_id), type_id)

  def from_id(self, cdata):
    return self.get(cdata)

  def from_key(self, cdata):
    return self.from_value(cdata.value)


class Native(object):
  """Encapsulates fetching a platform specific version of the native portion of the engine.
  """

  class Factory(Subsystem):
    options_scope = 'native-engine'

    @classmethod
    def subsystem_dependencies(cls):
      return (BinaryUtil.Factory,)

    @staticmethod
    def _default_native_engine_version():
      return pkg_resources.resource_string(__name__, 'native_engine_version').strip()

    @classmethod
    def register_options(cls, register):
      register('--version', advanced=True, default=cls._default_native_engine_version(),
               help='Native engine version.')
      register('--supportdir', advanced=True, default='bin/native-engine',
               help='Find native engine binaries under this dir. Used as part of the path to '
                    'lookup the binary with --binary-util-baseurls and --pants-bootstrapdir.')
      register('--visualize-to', default=None, type=dir_option,
               help='A directory to write execution graphs to as `dot` files. The contents '
                    'of the directory will be overwritten if any filenames collide.')

    def create(self):
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return Native(binary_util, options.version, options.supportdir, options.visualize_to)

  def __init__(self, binary_util, version, supportdir, visualize_to_dir):
    """
    :param binary_util: The BinaryUtil subsystem instance for binary retrieval.
    :param version: The binary version of the native engine.
    :param supportdir: The supportdir for the native engine.
    :param visualize_to_dir: An existing directory (or None) to visualize executions to.
    """
    self._binary_util = binary_util
    self._version = version
    self._supportdir = supportdir
    self._visualize_to_dir = visualize_to_dir

    self._lib_field = None

  @property
  def visualize_to_dir(self):
    return self._visualize_to_dir

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

  def as_str(self, cdata):
    return _FFI.string(cdata)