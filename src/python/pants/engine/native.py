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
import traceback
from contextlib import closing

import cffi
import pkg_resources
import six

from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_mkdtemp
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
  Id       id_;
  TypeId   type_id;
} Key;

typedef struct {
  Key key;
} TypeConstraint;

typedef struct {
  Key key;
} Function;

typedef struct {
  Handle   handle;
} Value;

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
  _Bool  is_throw;
  Value  value;
} PyResult;

typedef struct {
  int64_t   hash_;
  Value     value;
  TypeId    type_id;
} Ident;

typedef void ExternContext;

// On the rust side the integration is defined in externs.rs
typedef void             (*extern_ptr_log)(ExternContext*, uint8_t, uint8_t*, uint64_t);
typedef Ident            (*extern_ptr_identify)(ExternContext*, Value*);
typedef _Bool            (*extern_ptr_equals)(ExternContext*, Value*, Value*);
typedef Value            (*extern_ptr_clone_val)(ExternContext*, Value*);
typedef void             (*extern_ptr_drop_handles)(ExternContext*, Handle*, uint64_t);
typedef Buffer           (*extern_ptr_type_to_str)(ExternContext*, TypeId);
typedef Buffer           (*extern_ptr_val_to_str)(ExternContext*, Value*);
typedef _Bool            (*extern_ptr_satisfied_by)(ExternContext*, Value*, Value*);
typedef _Bool            (*extern_ptr_satisfied_by_type)(ExternContext*, Value*, TypeId*);
typedef Value            (*extern_ptr_store_list)(ExternContext*, Value**, uint64_t, _Bool);
typedef Value            (*extern_ptr_store_bytes)(ExternContext*, uint8_t*, uint64_t);
typedef Value            (*extern_ptr_store_i32)(ExternContext*, int32_t);
typedef Value            (*extern_ptr_project)(ExternContext*, Value*, uint8_t*, uint64_t, TypeId*);
typedef ValueBuffer      (*extern_ptr_project_multi)(ExternContext*, Value*, uint8_t*, uint64_t);
typedef Value            (*extern_ptr_project_ignoring_type)(ExternContext*, Value*, uint8_t*, uint64_t);
typedef Value            (*extern_ptr_create_exception)(ExternContext*, uint8_t*, uint64_t);
typedef PyResult         (*extern_ptr_call)(ExternContext*, Value*, Value*, uint64_t);
typedef PyResult         (*extern_ptr_eval)(ExternContext*, uint8_t*, uint64_t);

typedef void Tasks;
typedef void Scheduler;
typedef void ExecutionRequest;

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
                 extern_ptr_call,
                 extern_ptr_eval,
                 extern_ptr_identify,
                 extern_ptr_equals,
                 extern_ptr_clone_val,
                 extern_ptr_drop_handles,
                 extern_ptr_type_to_str,
                 extern_ptr_val_to_str,
                 extern_ptr_satisfied_by,
                 extern_ptr_satisfied_by_type,
                 extern_ptr_store_list,
                 extern_ptr_store_bytes,
                 extern_ptr_store_i32,
                 extern_ptr_project,
                 extern_ptr_project_ignoring_type,
                 extern_ptr_project_multi,
                 extern_ptr_create_exception,
                 TypeId);

Key externs_key_for(Value);
Value externs_val_for(Key);

Tasks* tasks_create(void);
void tasks_task_begin(Tasks*, Function, TypeConstraint);
void tasks_add_select(Tasks*, TypeConstraint);
void tasks_add_select_variant(Tasks*, TypeConstraint, Buffer);
void tasks_add_select_dependencies(Tasks*, TypeConstraint, TypeConstraint, Buffer, TypeIdBuffer);
void tasks_add_select_transitive(Tasks*, TypeConstraint, TypeConstraint, Buffer, TypeIdBuffer);
void tasks_add_select_projection(Tasks*, TypeConstraint, TypeId, Buffer, TypeConstraint);
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


ExecutionRequest* execution_request_create(void);
void execution_request_destroy(ExecutionRequest*);

uint64_t graph_len(Scheduler*);
uint64_t graph_invalidate(Scheduler*, BufferBuffer);
void graph_visualize(Scheduler*, ExecutionRequest*, char*);
void graph_trace(Scheduler*, ExecutionRequest*, char*);

PyResult  execution_add_root_select(Scheduler*, ExecutionRequest*, Key, TypeConstraint);
RawNodes* execution_execute(Scheduler*, ExecutionRequest*);

Value validator_run(Scheduler*);

void rule_graph_visualize(Scheduler*, TypeIdBuffer, char*);
void rule_subgraph_visualize(Scheduler*, TypeId, TypeConstraint, char*);

void nodes_destroy(RawNodes*);

void set_panic_handler(void);

void lease_files_in_graph(Scheduler*);

void garbage_collect_store(Scheduler*);
'''

CFFI_EXTERNS = '''
extern "Python" {
  void             extern_log(ExternContext*, uint8_t, uint8_t*, uint64_t);
  PyResult         extern_call(ExternContext*, Value*, Value*, uint64_t);
  PyResult         extern_eval(ExternContext*, uint8_t*, uint64_t);
  Ident            extern_identify(ExternContext*, Value*);
  _Bool            extern_equals(ExternContext*, Value*, Value*);
  Value            extern_clone_val(ExternContext*, Value*);
  void             extern_drop_handles(ExternContext*, Handle*, uint64_t);
  Buffer           extern_type_to_str(ExternContext*, TypeId);
  Buffer           extern_val_to_str(ExternContext*, Value*);
  _Bool            extern_satisfied_by(ExternContext*, Value*, Value*);
  _Bool            extern_satisfied_by_type(ExternContext*, Value*, TypeId*);
  Value            extern_store_list(ExternContext*, Value**, uint64_t, _Bool);
  Value            extern_store_bytes(ExternContext*, uint8_t*, uint64_t);
  Value            extern_store_i32(ExternContext*, int32_t);
  Value            extern_project(ExternContext*, Value*, uint8_t*, uint64_t, TypeId*);
  Value            extern_project_ignoring_type(ExternContext*, Value*, uint8_t*, uint64_t);
  ValueBuffer      extern_project_multi(ExternContext*, Value*, uint8_t*, uint64_t);
  Value            extern_create_exception(ExternContext*, uint8_t*, uint64_t);
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

  with temporary_dir() as tempdir:
    temp_output_prefix = os.path.join(tempdir, module_name)
    real_output_prefix = os.path.join(output_dir, module_name)
    temp_c_file = '{}.c'.format(temp_output_prefix)
    c_file = '{}.c'.format(real_output_prefix)
    env_script = '{}.cflags'.format(real_output_prefix)

    ffibuilder = cffi.FFI()
    ffibuilder.cdef(CFFI_TYPEDEFS)
    ffibuilder.cdef(CFFI_HEADERS)
    ffibuilder.cdef(CFFI_EXTERNS)
    ffibuilder.set_source(module_name, CFFI_TYPEDEFS + CFFI_HEADERS)
    ffibuilder.emit_c_code(six.binary_type(temp_c_file))

    # Work around https://github.com/rust-lang/rust/issues/36342 by renaming initnative_engine to
    # wrapped_initnative_engine so that the rust code can define the symbol initnative_engine.
    #
    # If we dont do this, we end up at the mercy of the implementation details of rust's stripping
    # and LTO. In the past we have found ways to trick it into not stripping symbols which was handy
    # (it kept the binary working) but inconvenient (it was relying on unspecified behavior, it meant
    # our binaries couldn't be stripped which inflated them by 2~3x, and it reduced the amount of LTO
    # we could use, which led to unmeasured performance hits).
    def rename_symbol_in_file(f):
      with open(f, 'rb') as fh:
        for line in fh:
          if line.startswith(b'init{}'.format(module_name)):
            yield 'wrapped_' + line
          else:
            yield line
    file_content = ''.join(rename_symbol_in_file(temp_c_file))

  _replace_file(c_file, file_content)

  # Write a shell script to be sourced at build time that contains inherited CFLAGS.
  _replace_file(env_script, get_build_cflags())


def _replace_file(path, content):
  """Writes a file if it doesn't already exist with the same content.

  This is useful because cargo uses timestamps to decide whether to compile things."""
  if os.path.exists(path):
    with open(path, 'rb') as f:
      if content == f.read():
        print("Not overwriting {} because it is unchanged".format(path), file=sys.stderr)
        return

  with open(path, 'wb') as f:
    f.write(content)


def _initialize_externs(ffi):
  """Initializes extern callbacks given a CFFI handle."""

  def to_py_str(msg_ptr, msg_len):
    return bytes(ffi.buffer(msg_ptr, msg_len)).decode('utf-8')

  def call(c, func, args):
    try:
      val = func(*args)
      is_throw = False
    except Exception as e:
      val = e
      is_throw = True
      e._formatted_exc = traceback.format_exc()

    return PyResult(is_throw, c.to_value(val))

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
  def extern_identify(context_handle, val):
    """Return an Ident containing a clone of the Value with its __hash__ and TypeId."""
    c = ffi.from_handle(context_handle)
    obj = ffi.from_handle(val.handle)
    hash_ = hash(obj)
    cloned = c.to_value(obj)
    type_id = c.to_id(type(obj))
    return (hash_, cloned, TypeId(type_id))

  @ffi.def_extern()
  def extern_equals(context_handle, val1, val2):
    """Return true if the given Values are __eq__."""
    return ffi.from_handle(val1.handle) == ffi.from_handle(val2.handle)

  @ffi.def_extern()
  def extern_clone_val(context_handle, val):
    """Clone the given Value."""
    c = ffi.from_handle(context_handle)
    return c.to_value(ffi.from_handle(val.handle))

  @ffi.def_extern()
  def extern_drop_handles(context_handle, handles_ptr, handles_len):
    """Drop the given Handles."""
    c = ffi.from_handle(context_handle)
    handles = ffi.unpack(handles_ptr, handles_len)
    c.drop_handles(handles)

  @ffi.def_extern()
  def extern_type_to_str(context_handle, type_id):
    """Given a TypeId, write type.__name__ and return it."""
    c = ffi.from_handle(context_handle)
    return c.utf8_buf(six.text_type(c.from_id(type_id.id_).__name__))

  @ffi.def_extern()
  def extern_val_to_str(context_handle, val):
    """Given a Value for `obj`, write str(obj) and return it."""
    c = ffi.from_handle(context_handle)
    return c.utf8_buf(six.text_type(c.from_value(val)))

  @ffi.def_extern()
  def extern_satisfied_by(context_handle, constraint_val, val):
    """Given a TypeConstraint and a Value return constraint.satisfied_by(value)."""
    constraint = ffi.from_handle(constraint_val.handle)
    return constraint.satisfied_by(ffi.from_handle(val.handle))

  @ffi.def_extern()
  def extern_satisfied_by_type(context_handle, constraint_val, cls_id):
    """Given a TypeConstraint and a TypeId, return constraint.satisfied_by_type(type_id)."""
    c = ffi.from_handle(context_handle)
    constraint = ffi.from_handle(constraint_val.handle)
    return constraint.satisfied_by_type(c.from_id(cls_id.id_))

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
  def extern_store_i32(context_handle, i32):
    """Given a context and int32_t, return a new Value to represent the int32_t."""
    c = ffi.from_handle(context_handle)
    return c.to_value(i32)

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
  def extern_call(context_handle, func, args_ptr, args_len):
    """Given a callable, call it."""
    c = ffi.from_handle(context_handle)
    runnable = c.from_value(func)
    args = tuple(c.from_value(arg) for arg in ffi.unpack(args_ptr, args_len))
    return call(c, runnable, args)

  @ffi.def_extern()
  def extern_eval(context_handle, python_code_str_ptr, python_code_str_len):
    """Given an evalable string, eval it and return a Value for its result."""
    c = ffi.from_handle(context_handle)
    return call(c, eval, [to_py_str(python_code_str_ptr, python_code_str_len)])


class Value(datatype('Value', ['handle'])):
  """Corresponds to the native object of the same name."""


class Key(datatype('Key', ['id_', 'type_id'])):
  """Corresponds to the native object of the same name."""


class Function(datatype('Function', ['key'])):
  """Corresponds to the native object of the same name."""


class TypeConstraint(datatype('TypeConstraint', ['key'])):
  """Corresponds to the native object of the same name."""


class TypeId(datatype('TypeId', ['id_'])):
  """Corresponds to the native object of the same name."""


class PyResult(datatype('PyResult', ['is_throw', 'value'])):
  """Corresponds to the native object of the same name."""


class ExternContext(object):
  """A wrapper around python objects used in static extern functions in this module.

  See comments in `src/rust/engine/src/interning.rs` for more information on the relationship
  between `Key`s and `Value`s.
  """

  def __init__(self, ffi, lib):
    """
    :param CompiledCFFI ffi: The CFFI handle to the compiled native engine lib.
    """
    self._ffi = ffi
    self._lib = lib

    # A handle to this object to ensure that the native wrapper survives at least as
    # long as this object.
    self._handle = self._ffi.new_handle(self)

    # A lookup table for `id(type) -> types`.
    self._types = {}

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

  def vals_buf(self, vals):
    buf = self._ffi.new('Value[]', vals)
    return (buf, len(vals), self.to_value(buf))

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

  def to_id(self, typ):
    type_id = id(typ)
    self._types[type_id] = typ
    return type_id

  def from_id(self, type_id):
    return self._types[type_id]

  def to_key(self, obj):
    cdata = self._lib.externs_key_for(self.to_value(obj))
    return Key(cdata.id_, TypeId(cdata.type_id.id_))

  def from_key(self, key):
    return Value(self._lib.externs_val_for(key).handle)


class Native(object):
  """Encapsulates fetching a platform specific version of the native portion of the engine."""

  @staticmethod
  def create(bootstrap_options):
    """:param options: Any object that provides access to bootstrap option values."""
    return Native(bootstrap_options.native_engine_visualize_to)

  def __init__(self, visualize_to_dir):
    """
    :param visualize_to_dir: An existing directory (or None) to visualize executions to.
    """
    self._visualize_to_dir = visualize_to_dir

  @property
  def visualize_to_dir(self):
    return self._visualize_to_dir

  @memoized_property
  def binary(self):
    """Load and return the path to the native engine binary."""
    lib_name = '{}.so'.format(NATIVE_ENGINE_MODULE)
    lib_path = os.path.join(safe_mkdtemp(), lib_name)
    with closing(pkg_resources.resource_stream(__name__, lib_name)) as input_fp:
      with open(lib_path, 'wb') as output_fp:
        output_fp.write(input_fp.read())
    return lib_path

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
      context = ExternContext(self.ffi, self.lib)
      self.lib.externs_set(context._handle,
                           self.ffi_lib.extern_log,
                           self.ffi_lib.extern_call,
                           self.ffi_lib.extern_eval,
                           self.ffi_lib.extern_identify,
                           self.ffi_lib.extern_equals,
                           self.ffi_lib.extern_clone_val,
                           self.ffi_lib.extern_drop_handles,
                           self.ffi_lib.extern_type_to_str,
                           self.ffi_lib.extern_val_to_str,
                           self.ffi_lib.extern_satisfied_by,
                           self.ffi_lib.extern_satisfied_by_type,
                           self.ffi_lib.extern_store_list,
                           self.ffi_lib.extern_store_bytes,
                           self.ffi_lib.extern_store_i32,
                           self.ffi_lib.extern_project,
                           self.ffi_lib.extern_project_ignoring_type,
                           self.ffi_lib.extern_project_multi,
                           self.ffi_lib.extern_create_exception,
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

  def new_execution_request(self):
    return self.gc(self.lib.execution_request_create(), self.lib.execution_request_destroy)

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
                    construct_process_result,
                    constraint_has_products,
                    constraint_address,
                    constraint_variants,
                    constraint_path_globs,
                    constraint_snapshot,
                    constraint_snapshots,
                    constraint_files_content,
                    constraint_dir,
                    constraint_file,
                    constraint_link,
                    constraint_process_request,
                    constraint_process_result):
    """Create and return an ExternContext and native Scheduler."""

    def func(constraint):
      return Function(self.context.to_key(constraint))
    def tc(constraint):
      return TypeConstraint(self.context.to_key(constraint))

    scheduler = self.lib.scheduler_create(
        tasks,
        # Constructors/functions.
        func(construct_snapshot),
        func(construct_snapshots),
        func(construct_file_content),
        func(construct_files_content),
        func(construct_path_stat),
        func(construct_dir),
        func(construct_file),
        func(construct_link),
        func(construct_process_result),
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
        tc(constraint_process_request),
        tc(constraint_process_result),
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
    if os.getenv("RUST_BACKTRACE", "0") != "1":
      # The panic handler hides a lot of rust tracing which may be useful.
      # Don't activate it when the user explicitly asks for rust backtraces.
      self.lib.set_panic_handler()
