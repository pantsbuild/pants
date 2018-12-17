# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from abc import abstractmethod, abstractproperty
from builtins import object

from pants.engine.rules import SingletonRule
from pants.util.meta import AbstractClass, classproperty
from pants.util.memo import memoized_classproperty
from pants.util.objects import datatype, enum
from pants.util.osutil import all_normalized_os_names, get_normalized_os_name
from pants.util.strutil import create_path_env_var


class Platform(enum('normalized_os_name', all_normalized_os_names())):

  default_value = get_normalized_os_name()


def _list_field(func):
  """A decorator for methods corresponding to list-valued fields of an `ExtensibleAlgebraic`.

  The result is also wrapped in `abstractproperty`.
  """
  wrapped = abstractproperty(func)
  wrapped._field_type = 'list'
  return wrapped


def _algebraic_data(metaclass):
  """A class decorator to pull out `_list_fields` from a mixin class for use with a `datatype`.
  """
  def wrapper(cls):
    cls.__bases__ += (metaclass,)
    cls._list_fields = metaclass._list_fields
    return cls
  return wrapper


class _ExtensibleAlgebraic(AbstractClass):
  """A mixin to make it more concise to coalesce datatypes with related collection fields."""

  # NB: prototypal inheritance seems *deeply* linked with the idea here!

  @memoized_classproperty
  def _list_fields(cls):
    all_list_fields = []
    for field_name in cls.__abstractmethods__:
      f = getattr(cls, field_name)
      if getattr(f, '_field_type', None) == 'list':
        all_list_fields.append(field_name)
    return frozenset(all_list_fields)

  @abstractmethod
  def copy(self, **kwargs):
    """Analogous to a `datatype()`'s `copy()` method."""
    raise NotImplementedError('copy() must be implemented by subclasses of _ExtensibleAlgebraic!')

  def _single_list_field_operation(self, field_name, list_value, prepend=True):
    assert(field_name in self._list_fields)
    cur_value = getattr(self, field_name)

    if prepend:
      new_value = list_value + cur_value
    else:
      new_value = cur_value + list_value

    arg_dict = {field_name: new_value}
    return self.copy(**arg_dict)

  def prepend_field(self, field_name, list_value):
    """Return a copy of this object with `list_value` prepended to the field named `field_name`."""
    return self._single_list_field_operation(field_name, list_value, prepend=True)

  def append_field(self, field_name, list_value):
    """Return a copy of this object with `list_value` appended to the field named `field_name`."""
    return self._single_list_field_operation(field_name, list_value, prepend=False)

  def sequence(self, other, exclude_list_fields=None):
    """Return a copy of this object which combines all the fields common to both `self` and `other`.

    List fields will be concatenated.

    The return type of this method is the type of `self`, but the `other` can be any
    `_ExtensibleAlgebraic` instance.
    """
    exclude_list_fields = exclude_list_fields or []
    overwrite_kwargs = {}

    shared_list_fields = (self._list_fields
                          & other._list_fields
                          - frozenset(exclude_list_fields))
    for list_field_name in shared_list_fields:
      lhs_value = getattr(self, list_field_name)
      rhs_value = getattr(other, list_field_name)
      if rhs_value is None:
        raise Exception('self: {}, other: {}, shared_list_fields: {}, lhs_value: {}, rhs_value: {}'
                        .format(self, other, shared_list_fields, lhs_value, rhs_value))
      overwrite_kwargs[list_field_name] = lhs_value + rhs_value

    return self.copy(**overwrite_kwargs)


class _Executable(_ExtensibleAlgebraic):

  @_list_field
  def path_entries(self):
    """A list of directory paths containing this executable, to be used in a subprocess's PATH.

    This may be multiple directories, e.g. if the main executable program invokes any subprocesses.

    :rtype: list of str
    """

  @abstractproperty
  def exe_filename(self):
    """The "entry point" -- which file to invoke when PATH is set to `path_entries()`.

    :rtype: str
    """
    raise NotImplementedError('exe_filename is a scalar field of _Executable!')

  # TODO: rename this to 'runtime_library_dirs'!
  @_list_field
  def library_dirs(self):
    """Directories containing shared libraries that must be on the runtime library search path.

    Note: this is for libraries needed for the current _Executable to run -- see _LinkerMixin below
    for libraries that are needed at link time.
    :rtype: list of str
    """
    raise NotImplementedError('library_dirs is a list field of _Executable!')

  @_list_field
  def extra_args(self):
    """Additional arguments used when invoking this _Executable.

    These are typically placed before the invocation-specific command line arguments.

    :rtype: list of str
    """
    raise NotImplementedError('extra_args is a list field of _Executable!')

  _platform = Platform.create()

  @property
  def as_invocation_environment_dict(self):
    """A dict to use as this _Executable's execution environment.

    :rtype: dict of string -> string
    """
    lib_env_var = self._platform.resolve_for_enum_variant({
      'darwin': 'DYLD_LIBRARY_PATH',
      'linux': 'LD_LIBRARY_PATH',
    })
    return {
      'PATH': create_path_env_var(self.path_entries),
      lib_env_var: create_path_env_var(self.library_dirs),
    }


@_algebraic_data(_Executable)
class Assembler(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'extra_args',
])): pass


class _LinkerMixin(_Executable):

  @_list_field
  def linking_library_dirs(self):
    """Directories to search for libraries needed at link time.

    :rtype: list of str
    """
    raise NotImplementedError('linking_library_dirs is a list field of _LinkerMixin!')

  @_list_field
  def extra_object_files(self):
    """A list of object files required to perform a successful link.

    This includes crti.o from libc for gcc on Linux, for example.

    :rtype: list of str
    """
    raise NotImplementedError('extra_object_files is a list field of _LinkerMixin!')

  @property
  def as_invocation_environment_dict(self):
    ret = super(_LinkerMixin, self).as_invocation_environment_dict.copy()

    full_library_path_dirs = self.linking_library_dirs + [
      os.path.dirname(f) for f in self.extra_object_files
    ]

    ret.update({
      'LDSHARED': self.exe_filename,
      'LIBRARY_PATH': create_path_env_var(full_library_path_dirs),
    })

    return ret


@_algebraic_data(_LinkerMixin)
class Linker(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'linking_library_dirs',
    'extra_args',
    'extra_object_files',
])): pass


class _CompilerMixin(_Executable):

  @_list_field
  def include_dirs(self):
    """Directories to search for header files to #include during compilation.

    :rtype: list of str
    """
    raise NotImplementedError('include_dirs is a list field of _CompilerMixin!')

  @property
  def as_invocation_environment_dict(self):
    ret = super(_CompilerMixin, self).as_invocation_environment_dict.copy()

    if self.include_dirs:
      ret['CPATH'] = create_path_env_var(self.include_dirs)

    return ret


@_algebraic_data(_CompilerMixin)
class CCompiler(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'include_dirs',
    'extra_args',
])):

  @property
  def as_invocation_environment_dict(self):
    ret = super(CCompiler, self).as_invocation_environment_dict.copy()

    ret['CC'] = self.exe_filename

    return ret


@_algebraic_data(_CompilerMixin)
class CppCompiler(datatype([
    'path_entries',
    'exe_filename',
    'library_dirs',
    'include_dirs',
    'extra_args',
])):

  @property
  def as_invocation_environment_dict(self):
    ret = super(CppCompiler, self).as_invocation_environment_dict.copy()

    ret['CXX'] = self.exe_filename

    return ret


class CToolchain(datatype([('c_compiler', CCompiler), ('c_linker', Linker)])): pass


class CppToolchain(datatype([('cpp_compiler', CppCompiler), ('cpp_linker', Linker)])): pass


# TODO: make this an @rule, after we can automatically produce LibcDev and other subsystems in the
# v2 engine (see #5788).
class HostLibcDev(datatype(['crti_object', 'fingerprint'])): pass


def create_native_environment_rules():
  return [
    SingletonRule(Platform, Platform.create()),
  ]
