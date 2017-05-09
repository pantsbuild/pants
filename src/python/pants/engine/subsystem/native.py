# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import importlib
import logging
import os
import sys
import sysconfig
import threading
import traceback

import cffi
import pkg_resources
import six

from pants.binaries.binary_util import BinaryUtil
from pants.engine.storage import Storage
from pants.option.custom_types import dir_option
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import safe_mkdir
from pants.util.memo import memoized_property
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


NATIVE_ENGINE_MODULE = 'native_engine'


CFFI_TYPEDEFS = '''
typedef uint64_t   Id;
typedef void*      Handle;

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
  Handle   handle;
} Value;

typedef struct {
  Id       id_;
  TypeId   type_id;
} Key;

typedef struct {
  uint8_t*  bytes_ptr;
  uint64_t  bytes_len;
  Value     handle_;
} Buffer;

typedef struct {
  Value*     values_ptr;
  uint64_t   values_len;
  Value      handle_;
} ValueBuffer;

typedef struct {
  TypeId*     ids_ptr;
  uint64_t    ids_len;
  Value       handle_;
} TypeIdBuffer;

typedef struct {
  Buffer*     bufs_ptr;
  uint64_t    bufs_len;
  Value       handle_;
} BufferBuffer;

typedef struct {
  Value  value;
  _Bool  is_throw;
  Buffer traceback;
} RunnableComplete;

typedef void ExternContext;

// On the rust side the integration is defined in externs.rs
typedef void             (*extern_ptr_log)(ExternContext*, uint8_t, uint8_t*, uint64_t);
typedef Key              (*extern_ptr_key_for)(ExternContext*, Value*);
typedef Value            (*extern_ptr_val_for)(ExternContext*, Key*);
typedef Value            (*extern_ptr_clone_val)(ExternContext*, Value*);
typedef void             (*extern_ptr_drop_handles)(ExternContext*, Handle*, uint64_t);
typedef Buffer           (*extern_ptr_id_to_str)(ExternContext*, Id);
typedef Buffer           (*extern_ptr_val_to_str)(ExternContext*, Value*);
typedef _Bool            (*extern_ptr_satisfied_by)(ExternContext*, TypeConstraint*, Value*);
typedef _Bool            (*extern_ptr_satisfied_by_type)(ExternContext*, TypeConstraint*, TypeId*);
typedef Value            (*extern_ptr_store_list)(ExternContext*, Value**, uint64_t, _Bool);
typedef Value            (*extern_ptr_store_bytes)(ExternContext*, uint8_t*, uint64_t);
typedef Value            (*extern_ptr_project)(ExternContext*, Value*, uint8_t*, uint64_t, TypeId*);
typedef ValueBuffer      (*extern_ptr_project_multi)(ExternContext*, Value*, uint8_t*, uint64_t);
typedef Value            (*extern_ptr_project_ignoring_type)(ExternContext*, Value*, uint8_t*, uint64_t);
typedef Value            (*extern_ptr_create_exception)(ExternContext*, uint8_t*, uint64_t);
typedef RunnableComplete (*extern_ptr_invoke_runnable)(ExternContext*, Value*, Value*, uint64_t, _Bool);

typedef void Tasks;
typedef void Scheduler;

typedef struct {
  uint64_t runnable_count;
  uint64_t scheduling_iterations;
} ExecutionStat;

typedef struct {
  Key             subject;
  TypeConstraint  product;
  uint8_t         state_tag;
  Value           state_value;
} RawNode;

typedef struct {
  RawNode*  nodes_ptr;
  uint64_t  nodes_len;
  // NB: there are more fields in this struct, but we can safely (?)
  // ignore them because we never have collections of this type.
} RawNodes;
'''

CFFI_HEADERS = '''
void externs_set(ExternContext*,
                 extern_ptr_log,
                 extern_ptr_key_for,
                 extern_ptr_val_for,
                 extern_ptr_clone_val,
                 extern_ptr_drop_handles,
                 extern_ptr_id_to_str,
                 extern_ptr_val_to_str,
                 extern_ptr_satisfied_by,
                 extern_ptr_satisfied_by_type,
                 extern_ptr_store_list,
                 extern_ptr_store_bytes,
                 extern_ptr_project,
                 extern_ptr_project_ignoring_type,
                 extern_ptr_project_multi,
                 extern_ptr_create_exception,
                 extern_ptr_invoke_runnable,
                 TypeId);

Tasks* tasks_create();
void tasks_task_begin(Tasks*, Function, TypeConstraint);
void tasks_add_select(Tasks*, TypeConstraint);
void tasks_add_select_variant(Tasks*, TypeConstraint, Buffer);
void tasks_add_select_dependencies(Tasks*, TypeConstraint, TypeConstraint, Buffer, TypeIdBuffer);
void tasks_add_select_transitive(Tasks*, TypeConstraint, TypeConstraint, Buffer, TypeIdBuffer);
void tasks_add_select_projection(Tasks*, TypeConstraint, TypeConstraint, Buffer, TypeConstraint);
void tasks_task_end(Tasks*);
void tasks_singleton_add(Tasks*, Value, TypeConstraint);
void tasks_destroy(Tasks*);

Scheduler* scheduler_create(Tasks*,
                            Function,
                            Function,
                            Function,
                            Function,
                            Function,
                            Function,
                            Function,
                            Function,
                            TypeConstraint,
                            TypeConstraint,
                            TypeConstraint,
                            TypeConstraint,
                            TypeConstraint,
                            TypeConstraint,
                            TypeConstraint,
                            TypeConstraint,
                            TypeConstraint,
                            TypeConstraint,
                            TypeId,
                            TypeId,
                            Buffer,
                            Buffer,
                            BufferBuffer,
                            TypeIdBuffer);
void scheduler_pre_fork(Scheduler*);
void scheduler_destroy(Scheduler*);

uint64_t graph_len(Scheduler*);
uint64_t graph_invalidate(Scheduler*, BufferBuffer);
void graph_visualize(Scheduler*, char*);
void graph_trace(Scheduler*, char*);

void execution_reset(Scheduler*);
void execution_add_root_select(Scheduler*, Key, TypeConstraint);
void execution_add_root_select_dependencies(Scheduler*,
                                            Key,
                                            TypeConstraint,
                                            TypeConstraint,
                                            Buffer,
                                            TypeIdBuffer);
ExecutionStat execution_execute(Scheduler*);
RawNodes* execution_roots(Scheduler*);

Value validator_run(Scheduler*);

void rule_graph_visualize(Scheduler*, TypeIdBuffer, char*);
void rule_subgraph_visualize(Scheduler*, TypeId, TypeConstraint, char*);

void nodes_destroy(RawNodes*);

void set_panic_handler();
'''

CFFI_EXTERNS = '''
extern "Python" {
  void             extern_log(ExternContext*, uint8_t, uint8_t*, uint64_t);
  Key              extern_key_for(ExternContext*, Value*);
  Value            extern_val_for(ExternContext*, Key*);
  Value            extern_clone_val(ExternContext*, Value*);
  void             extern_drop_handles(ExternContext*, Handle*, uint64_t);
  Buffer           extern_id_to_str(ExternContext*, Id);
  Buffer           extern_val_to_str(ExternContext*, Value*);
  _Bool            extern_satisfied_by(ExternContext*, TypeConstraint*, Value*);
  _Bool            extern_satisfied_by_type(ExternContext*, TypeConstraint*, TypeId*);
  Value            extern_store_list(ExternContext*, Value**, uint64_t, _Bool);
  Value            extern_store_bytes(ExternContext*, uint8_t*, uint64_t);
  Value            extern_project(ExternContext*, Value*, uint8_t*, uint64_t, TypeId*);
  Value            extern_project_ignoring_type(ExternContext*, Value*, uint8_t*, uint64_t);
  ValueBuffer      extern_project_multi(ExternContext*, Value*, uint8_t*, uint64_t);
  Value            extern_create_exception(ExternContext*, uint8_t*, uint64_t);
  RunnableComplete extern_invoke_runnable(ExternContext*, Value*, Value*, uint64_t, _Bool);
}
'''


def get_build_cflags():
  """Synthesize a CFLAGS env var from the current python env for building of C modules."""
  return '{} {} -I{}'.format(
    sysconfig.get_config_var('BASECFLAGS'),
    sysconfig.get_config_var('OPT'),
    sysconfig.get_path('include')
  )


def bootstrap_c_source(output_dir, module_name=NATIVE_ENGINE_MODULE):
  """Bootstrap an external CFFI C source file."""
  safe_mkdir(output_dir)

  output_prefix = os.path.join(output_dir, module_name)
  c_file = '{}.c'.format(output_prefix)
  env_script = '{}.sh'.format(output_prefix)

  ffibuilder = cffi.FFI()
  ffibuilder.cdef(CFFI_TYPEDEFS)
  ffibuilder.cdef(CFFI_HEADERS)
  ffibuilder.cdef(CFFI_EXTERNS)
  ffibuilder.set_source(module_name, CFFI_TYPEDEFS + CFFI_HEADERS)
  ffibuilder.emit_c_code(six.binary_type(c_file))

  # Write a shell script to be sourced at build time that contains inherited CFLAGS.
  print('generating {}'.format(env_script))
  with open(env_script, 'wb') as f:
    f.write('export CFLAGS="{}"\n'.format(get_build_cflags()))


def _initialize_externs(ffi):
  """Initializes extern callbacks given a CFFI handle."""

  def to_py_str(msg_ptr, msg_len):
    return bytes(ffi.buffer(msg_ptr, msg_len)).decode('utf-8')

  @ffi.def_extern()
  def extern_log(context_handle, level, msg_ptr, msg_len):
    """Given a log level and utf8 message string, log it."""
    msg = bytes(ffi.buffer(msg_ptr, msg_len)).decode('utf-8')
    if level == 0:
      logger.debug(msg)
    elif level == 1:
      logger.info(msg)
    elif level == 2:
      logger.warn(msg)
    else:
      logger.critical(msg)

  @ffi.def_extern()
  def extern_key_for(context_handle, val):
    """Return a Key for a Value."""
    c = ffi.from_handle(context_handle)
    return c.to_key(c.from_value(val))

  @ffi.def_extern()
  def extern_val_for(context_handle, key):
    """Return a Value for a Key."""
    c = ffi.from_handle(context_handle)
    return c.to_value(c.from_key(key))

  @ffi.def_extern()
  def extern_clone_val(context_handle, val):
    """Clone the given Value."""
    c = ffi.from_handle(context_handle)
    return c.to_value(c.from_value(val))

  @ffi.def_extern()
  def extern_drop_handles(context_handle, handles_ptr, handles_len):
    """Drop the given Handles."""
    c = ffi.from_handle(context_handle)
    handles = ffi.unpack(handles_ptr, handles_len)
    c.drop_handles(handles)

  @ffi.def_extern()
  def extern_id_to_str(context_handle, id_):
    """Given an Id for `obj`, write str(obj) and return it."""
    c = ffi.from_handle(context_handle)
    return c.utf8_buf(six.text_type(c.from_id(id_)))

  @ffi.def_extern()
  def extern_val_to_str(context_handle, val):
    """Given a Value for `obj`, write str(obj) and return it."""
    c = ffi.from_handle(context_handle)
    return c.utf8_buf(six.text_type(c.from_value(val)))

  @ffi.def_extern()
  def extern_satisfied_by(context_handle, constraint_id, val):
    """Given a TypeConstraint and a Value return constraint.satisfied_by(value)."""
    c = ffi.from_handle(context_handle)
    return c.from_id(constraint_id.id_).satisfied_by(c.from_value(val))

  @ffi.def_extern()
  def extern_satisfied_by_type(context_handle, constraint_id, cls_id):
    """Given a TypeConstraint and a TypeId, return constraint.satisfied_by_type(type_id)."""
    c = ffi.from_handle(context_handle)
    return c.from_id(constraint_id.id_).satisfied_by_type(c.from_id(cls_id.id_))

  @ffi.def_extern()
  def extern_store_list(context_handle, vals_ptr_ptr, vals_len, merge):
    """Given storage and an array of Values, return a new Value to represent the list."""
    c = ffi.from_handle(context_handle)
    vals = tuple(c.from_value(val) for val in ffi.unpack(vals_ptr_ptr, vals_len))
    if merge:
      # Expect each obj to represent a list, and do a de-duping merge.
      merged_set = set()
      def merged():
        for outer_val in vals:
          for inner_val in outer_val:
            if inner_val in merged_set:
              continue
            merged_set.add(inner_val)
            yield inner_val
      vals = tuple(merged())
    return c.to_value(vals)

  @ffi.def_extern()
  def extern_store_bytes(context_handle, bytes_ptr, bytes_len):
    """Given a context and raw bytes, return a new Value to represent the content."""
    c = ffi.from_handle(context_handle)
    return c.to_value(bytes(ffi.buffer(bytes_ptr, bytes_len)))

  @ffi.def_extern()
  def extern_project(context_handle, val, field_str_ptr, field_str_len, type_id):
    """Given a Value for `obj`, a field name, and a type, project the field as a new Value."""
    c = ffi.from_handle(context_handle)
    obj = c.from_value(val)
    field_name = to_py_str(field_str_ptr, field_str_len)
    typ = c.from_id(type_id.id_)

    projected = getattr(obj, field_name)
    if type(projected) is not typ:
      projected = typ(projected)

    return c.to_value(projected)

  @ffi.def_extern()
  def extern_project_ignoring_type(context_handle, val, field_str_ptr, field_str_len):
    """Given a Value for `obj`, and a field name, project the field as a new Value."""
    c = ffi.from_handle(context_handle)
    obj = c.from_value(val)
    field_name = to_py_str(field_str_ptr, field_str_len)
    projected = getattr(obj, field_name)

    return c.to_value(projected)

  @ffi.def_extern()
  def extern_project_multi(context_handle, val, field_str_ptr, field_str_len):
    """Given a Key for `obj`, and a field name, project the field as a list of Keys."""
    c = ffi.from_handle(context_handle)
    obj = c.from_value(val)
    field_name = to_py_str(field_str_ptr, field_str_len)

    return c.vals_buf(tuple(c.to_value(p) for p in getattr(obj, field_name)))

  @ffi.def_extern()
  def extern_create_exception(context_handle, msg_ptr, msg_len):
    """Given a utf8 message string, create an Exception object."""
    c = ffi.from_handle(context_handle)
    msg = to_py_str(msg_ptr, msg_len)
    return c.to_value(Exception(msg))

  @ffi.def_extern()
  def extern_invoke_runnable(context_handle, func, args_ptr, args_len, cacheable):
    """Given a destructured rawRunnable, run it."""
    c = ffi.from_handle(context_handle)
    runnable = c.from_value(func)
    args = tuple(c.from_value(arg) for arg in ffi.unpack(args_ptr, args_len))

    try:
      val = runnable(*args)
      is_throw = False
      traceback_str = ''
    except Exception as e:
      val = e
      is_throw = True
      traceback_str = traceback.format_exc()

    return RunnableComplete(c.to_value(val), is_throw, c.utf8_buf(traceback_str))


class Value(datatype('Value', ['handle'])):
  """Corresponds to the native object of the same name."""


class Key(datatype('Key', ['id_', 'type_id'])):
  """Corresponds to the native object of the same name."""


class Function(datatype('Function', ['id_'])):
  """Corresponds to the native object of the same name."""


class TypeConstraint(datatype('TypeConstraint', ['id_'])):
  """Corresponds to the native object of the same name."""


class TypeId(datatype('TypeId', ['id_'])):
  """Corresponds to the native object of the same name."""


class RunnableComplete(datatype('RunnableComplete', ['value', 'is_throw', 'traceback'])):
  """Corresponds to the native object of the same name."""


class ObjectIdMap(object):
  """In the native context, assign and memoize python objects an unique unsigned-integer Id.

  Underlying, the id is uniquely derived from object's digest instead of using its hash code
  because the content may change and object's hash function could be overridden. In order not
  to return the stale object we trade performance for correctness.

  In the future, we could improve performance by only computing digests for mutable objects.
  For this reason referring an implementation-independent id instead of the digest in the native
  context is more flexible.
  """

  def __init__(self):
    # Objects indexed by their keys, i.e, content digests
    self._objects = Storage.create()
    # Memoized object Ids.
    self._id_to_key = dict()
    self._key_to_id = dict()
    self._next_id = 0

  def put(self, obj):
    key = self._objects.put(obj)
    new_id = self._next_id
    oid = self._key_to_id.setdefault(key, new_id)
    if oid is not new_id:
      # Object already existed.
      return oid

    # Object is new/unique.
    self._id_to_key[oid] = key
    self._next_id += 1
    return oid

  def get(self, oid):
    return self._objects.get(self._id_to_key[oid])


class ExternContext(object):
  """A wrapper around python objects used in static extern functions in this module."""

  def __init__(self, ffi):
    """
    :param CompiledCFFI ffi: The CFFI handle to the compiled native engine lib.
    """
    self._ffi = ffi

    # A handle to this object to ensure that the native wrapper survives at least as
    # long as this object.
    self.handle = self._ffi.new_handle(self)

    # The native code will invoke externs concurrently, so locking is needed around
    # datastructures in this context.
    self._lock = threading.RLock()

    # Memoized object Ids.
    self._id_generator = 0
    self._id_to_obj = dict()
    self._obj_to_id = dict()
    self._object_id_map = ObjectIdMap()

    # Outstanding FFI object handles.
    self._handles = set()

  def buf(self, bytestring):
    buf = self._ffi.new('uint8_t[]', bytestring)
    return (buf, len(bytestring), self.to_value(buf))

  def utf8_buf(self, string):
    return self.buf(string.encode('utf-8'))

  def utf8_buf_buf(self, strings):
    bufs = [self.utf8_buf(string) for string in strings]
    buf_buf = self._ffi.new('Buffer[]', bufs)
    return (buf_buf, len(bufs), self.to_value(buf_buf))

  def vals_buf(self, keys):
    buf = self._ffi.new('Value[]', keys)
    return (buf, len(keys), self.to_value(buf))

  def type_ids_buf(self, types):
    buf = self._ffi.new('TypeId[]', types)
    return (buf, len(types), self.to_value(buf))

  def to_value(self, obj):
    handle = self._ffi.new_handle(obj)
    self._handles.add(handle)
    return Value(handle)

  def from_value(self, val):
    return self._ffi.from_handle(val.handle)

  def drop_handles(self, handles):
    self._handles -= set(handles)

  def put(self, obj):
    with self._lock:
      # If we encounter an existing id, return it.
      return self._object_id_map.put(obj)

  def get(self, id_):
    return self._object_id_map.get(id_)

  def to_id(self, typ):
    return self.put(typ)

  def to_key(self, obj):
    type_id = TypeId(self.put(type(obj)))
    return Key(self.put(obj), type_id)

  def from_id(self, cdata):
    return self.get(cdata)

  def from_key(self, cdata):
    return self.get(cdata.id_)


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
               help='A directory to write execution and rule graphs to as `dot` files. The contents '
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

  @property
  def visualize_to_dir(self):
    return self._visualize_to_dir

  @memoized_property
  def binary(self):
    """Load and return the path to the native engine binary."""
    return self._binary_util.select_binary(self._supportdir,
                                           self._version,
                                           '{}.so'.format(NATIVE_ENGINE_MODULE))

  @memoized_property
  def lib(self):
    """Load and return the native engine module."""
    return self.ffi.dlopen(self.binary)

  @memoized_property
  def ffi(self):
    """A CompiledCFFI handle as imported from the native engine python module."""
    ffi = getattr(self._ffi_module, 'ffi')
    _initialize_externs(ffi)
    return ffi

  @memoized_property
  def ffi_lib(self):
    """A CFFI Library handle as imported from the native engine python module."""
    return getattr(self._ffi_module, 'lib')

  @memoized_property
  def _ffi_module(self):
    """Load the native engine as a python module and register CFFI externs."""
    native_bin_dir = os.path.dirname(self.binary)
    logger.debug('loading native engine python module from: %s', native_bin_dir)
    sys.path.insert(0, native_bin_dir)
    return importlib.import_module(NATIVE_ENGINE_MODULE)

  @memoized_property
  def context(self):
    # We statically initialize a ExternContext to correspond to the queue of dropped
    # Handles that the native code maintains.
    def init_externs():
      context = ExternContext(self.ffi)
      self.lib.externs_set(context.handle,
                           self.ffi_lib.extern_log,
                           self.ffi_lib.extern_key_for,
                           self.ffi_lib.extern_val_for,
                           self.ffi_lib.extern_clone_val,
                           self.ffi_lib.extern_drop_handles,
                           self.ffi_lib.extern_id_to_str,
                           self.ffi_lib.extern_val_to_str,
                           self.ffi_lib.extern_satisfied_by,
                           self.ffi_lib.extern_satisfied_by_type,
                           self.ffi_lib.extern_store_list,
                           self.ffi_lib.extern_store_bytes,
                           self.ffi_lib.extern_project,
                           self.ffi_lib.extern_project_ignoring_type,
                           self.ffi_lib.extern_project_multi,
                           self.ffi_lib.extern_create_exception,
                           self.ffi_lib.extern_invoke_runnable,
                           TypeId(context.to_id(str)))
      return context

    return self.ffi.init_once(init_externs, 'ExternContext singleton')

  def new(self, cdecl, init):
    return self.ffi.new(cdecl, init)

  def gc(self, cdata, destructor):
    """Register a method to be called when `cdata` is garbage collected.

    Returns a new reference that should be used in place of `cdata`.
    """
    return self.ffi.gc(cdata, destructor)

  def unpack(self, cdata_ptr, count):
    """Given a pointer representing an array, and its count of entries, return a list."""
    return self.ffi.unpack(cdata_ptr, count)

  def buffer(self, cdata):
    return self.ffi.buffer(cdata)

  def to_ids_buf(self, types):
    return self.context.type_ids_buf([TypeId(self.context.to_id(t)) for t in types])

  def new_tasks(self):
    return self.gc(self.lib.tasks_create(), self.lib.tasks_destroy)

  def new_scheduler(self,
                    tasks,
                    root_subject_types,
                    build_root,
                    work_dir,
                    ignore_patterns,
                    construct_snapshot,
                    construct_snapshots,
                    construct_file_content,
                    construct_files_content,
                    construct_path_stat,
                    construct_dir,
                    construct_file,
                    construct_link,
                    constraint_has_products,
                    constraint_address,
                    constraint_variants,
                    constraint_path_globs,
                    constraint_snapshot,
                    constraint_snapshots,
                    constraint_files_content,
                    constraint_dir,
                    constraint_file,
                    constraint_link):
    """Create and return an ExternContext and native Scheduler."""

    def tc(constraint):
      return TypeConstraint(self.context.to_id(constraint))

    scheduler = self.lib.scheduler_create(
        tasks,
        # Constructors/functions.
        Function(self.context.to_id(construct_snapshot)),
        Function(self.context.to_id(construct_snapshots)),
        Function(self.context.to_id(construct_file_content)),
        Function(self.context.to_id(construct_files_content)),
        Function(self.context.to_id(construct_path_stat)),
        Function(self.context.to_id(construct_dir)),
        Function(self.context.to_id(construct_file)),
        Function(self.context.to_id(construct_link)),
        # TypeConstraints.
        tc(constraint_address),
        tc(constraint_has_products),
        tc(constraint_variants),
        tc(constraint_path_globs),
        tc(constraint_snapshot),
        tc(constraint_snapshots),
        tc(constraint_files_content),
        tc(constraint_dir),
        tc(constraint_file),
        tc(constraint_link),
        # Types.
        TypeId(self.context.to_id(six.text_type)),
        TypeId(self.context.to_id(six.binary_type)),
        # Project tree.
        self.context.utf8_buf(build_root),
        self.context.utf8_buf(work_dir),
        self.context.utf8_buf_buf(ignore_patterns),
        self.to_ids_buf(root_subject_types),
      )
    return self.gc(scheduler, self.lib.scheduler_destroy)

  def set_panic_handler(self):
    self.lib.set_panic_handler()
