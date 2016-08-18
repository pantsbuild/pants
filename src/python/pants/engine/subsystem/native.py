# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem


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

    self._ffi_field = None
    self._lib_field = None

  @property
  def _ffi(self):
    if self._ffi_field is not None:
      return self._ffi_field

    from cffi import FFI

    self._ffi_field = FFI()
    # TODO: This definition is coupled to callers: should memoize it there.
    self._ffi_field.cdef(
        '''
        typedef uint64_t TypeId;

        typedef struct {
          char     digest_upper[32];
          char     digest_lower[32];
          TypeId   type_id;
        } Key;

        typedef uint64_t EntryId;
        typedef Key Field;

        typedef struct {
          Key*        func;
          Key*        args_ptr;
          uint64_t    args_len;
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
          // NB: there are more fields in this struct, but we can safely
          // ignore them because we never have collections of this type.
        } RawExecution;

        typedef struct {
          RawExecution execution;
          // NB: there are more fields in this struct, but we can safely
          // ignore them because we never have collections of this type.
        } RawScheduler;

        RawScheduler* scheduler_create(Key*,
                                       Field*,
                                       Field*,
                                       Field*,
                                       TypeId,
                                       TypeId,
                                       TypeId);
        void scheduler_destroy(RawScheduler*);

        void task_gen(RawScheduler*, Key*, TypeId);
        void task_end(RawScheduler*);

        uint64_t graph_len(RawScheduler*);

        void execution_reset(RawScheduler*);
        void execution_add_root_select(RawScheduler*, Key*, TypeId);
        void execution_add_root_select_dependencies(RawScheduler*,
                                                    Key*,
                                                    TypeId,
                                                    TypeId,
                                                    Field*);
        void execution_next(RawScheduler*,
                            EntryId*,
                            RawRunnable*,
                            uint64_t);
        '''
      )
    return self._ffi_field

  @property
  def lib(self):
    """Load and return the `libgraph` module."""
    if self._lib_field is None:
      binary = self._binary_util.select_binary(self._supportdir,
                                              self._version,
                                              'native-engine')
      self._lib_field = self._ffi.dlopen(binary)
    return self._lib_field

  def new(self, cdecl, init):
    return self._ffi.new(cdecl, init)

  def gc(self, cdata, destructor):
    """Register a method to be called when `cdata` is garbage collected.

    Returns a new reference that should be used in place of `cdata`.
    """
    return self._ffi.gc(cdata, destructor)

  def unpack(self, cdata_ptr, count):
    """Given a pointer representing an array, and its count of entries, return a list."""
    return self._ffi.unpack(cdata_ptr, count)
