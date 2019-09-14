# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from abc import ABC, abstractmethod

from pants.engine.platform import Platform
from pants.util.memo import memoized_classproperty
from pants.util.objects import datatype
from pants.util.strutil import create_path_env_var


class _list_field(property):
  """A decorator for methods corresponding to list-valued fields of an `ExtensibleAlgebraic`."""
  __isabstractmethod__ = True
  _field_type = 'list'


def _algebraic_data(metaclass):
  """A class decorator to pull out `_list_fields` from a mixin class for use with a `datatype`."""
  def wrapper(cls):
    cls.__bases__ += (metaclass,)
    cls._list_fields = metaclass._list_fields
    return cls
  return wrapper


# NB: prototypal inheritance seems *deeply* linked with the idea here!
# TODO: since we are calling these methods from other files, we should remove the leading underscore
# and add testing!
class _ExtensibleAlgebraic(ABC):
  """A mixin to make it more concise to coalesce datatypes with related collection fields."""

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
    """Implementations should have the same behavior as a `datatype()`'s `copy()` method."""

  class AlgebraicDataError(Exception): pass

  def _single_list_field_operation(self, field_name, list_value, prepend=True):
    if field_name not in self._list_fields:
      raise self.AlgebraicDataError(
        "Field '{}' is not in this object's set of declared list fields: {} (this object is : {})."
        .format(field_name, self._list_fields, self))
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

    The return type of this method is the type of `self` (or whatever `.copy()` returns), but the
    `other` argument can be any `_ExtensibleAlgebraic` instance.
    """
    exclude_list_fields = frozenset(exclude_list_fields or [])
    overwrite_kwargs = {}

    nonexistent_excluded_fields = exclude_list_fields - self._list_fields
    if nonexistent_excluded_fields:
      raise self.AlgebraicDataError(
        "Fields {} to exclude from a sequence() were not found in this object's list fields: {}. "
        "This object is {}, the other object is {}."
        .format(nonexistent_excluded_fields, self._list_fields, self, other))

    shared_list_fields = (self._list_fields
                          & other._list_fields
                          - exclude_list_fields)
    if not shared_list_fields:
      raise self.AlgebraicDataError(
        "Objects to sequence have no shared fields after excluding {}. "
        "This object is {}, with list fields: {}. "
        "The other object is {}, with list fields: {}."
        .format(exclude_list_fields, self, self._list_fields, other, other._list_fields))

    for list_field_name in shared_list_fields:
      lhs_value = getattr(self, list_field_name)
      rhs_value = getattr(other, list_field_name)
      overwrite_kwargs[list_field_name] = lhs_value + rhs_value

    return self.copy(**overwrite_kwargs)


class _Executable(_ExtensibleAlgebraic):

  @_list_field
  def path_entries(self):
    """A list of directory paths containing this executable, to be used in a subprocess's PATH.

    This may be multiple directories, e.g. if the main executable program invokes any subprocesses.

    :rtype: list of str
    """

  @property
  @abstractmethod
  def exe_filename(self):
    """The "entry point" -- which file to invoke when PATH is set to `path_entries()`.

    :rtype: str
    """

  @_list_field
  def runtime_library_dirs(self):
    """Directories containing shared libraries that must be on the runtime library search path.

    Note: this is for libraries needed for the current _Executable to run -- see _LinkerMixin below
    for libraries that are needed at link time.
    :rtype: list of str
    """

  @_list_field
  def extra_args(self):
    """Additional arguments used when invoking this _Executable.

    These are typically placed before the invocation-specific command line arguments.

    :rtype: list of str
    """

  _platform = Platform.current

  @property
  def invocation_environment_dict(self):
    """A dict to use as this _Executable's execution environment.

    This isn't made into an "algebraic" field because its contents (the keys of the dict) are
    generally known to the specific class which is overriding this property. Implementations of this
    property can then make use of the data in the algebraic fields to populate this dict.

    :rtype: dict of string -> string
    """
    return {
      'PATH': create_path_env_var(self.path_entries),
      self._platform.runtime_lib_path_env_var: create_path_env_var(self.runtime_library_dirs),
    }


@_algebraic_data(_Executable)
class Assembler(datatype([
    'path_entries',
    'exe_filename',
    'runtime_library_dirs',
    'extra_args',
])): pass


class _LinkerMixin(_Executable):

  @_list_field
  def linking_library_dirs(self):
    """Directories to search for libraries needed at link time.

    :rtype: list of str
    """

  @_list_field
  def extra_object_files(self):
    """A list of object files required to perform a successful link.

    This includes crti.o from libc for gcc on Linux, for example.

    :rtype: list of str
    """

  @property
  def invocation_environment_dict(self):
    ret = super(_LinkerMixin, self).invocation_environment_dict.copy()

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
    'runtime_library_dirs',
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

  @property
  def invocation_environment_dict(self):
    ret = super(_CompilerMixin, self).invocation_environment_dict.copy()

    if self.include_dirs:
      ret['CPATH'] = create_path_env_var(self.include_dirs)

    return ret


@_algebraic_data(_CompilerMixin)
class CCompiler(datatype([
    'path_entries',
    'exe_filename',
    'runtime_library_dirs',
    'include_dirs',
    'extra_args',
])):

  @property
  def invocation_environment_dict(self):
    ret = super().invocation_environment_dict.copy()

    ret['CC'] = self.exe_filename

    return ret


@_algebraic_data(_CompilerMixin)
class CppCompiler(datatype([
    'path_entries',
    'exe_filename',
    'runtime_library_dirs',
    'include_dirs',
    'extra_args',
])):

  @property
  def invocation_environment_dict(self):
    ret = super().invocation_environment_dict.copy()

    ret['CXX'] = self.exe_filename

    return ret


class CToolchain(datatype([('c_compiler', CCompiler), ('c_linker', Linker)])): pass


class CppToolchain(datatype([('cpp_compiler', CppCompiler), ('cpp_linker', Linker)])): pass


# TODO: make this an @rule, after we can automatically produce LibcDev and other subsystems in the
# v2 engine (see #5788).
class HostLibcDev(datatype(['crti_object', 'fingerprint'])): pass
