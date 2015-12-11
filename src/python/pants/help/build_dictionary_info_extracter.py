# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import inspect
import re
from collections import namedtuple

from pants.build_graph.target import Target
from pants.util.memo import memoized_method


class FunctionArg(namedtuple('_FunctionArg', ['name', 'description', 'has_default', 'default'])):
  """An argument to a function."""
  pass


class TargetTypeInfo(namedtuple('_TargetTypeInfo', ['build_file_alias', 'description'])):
  """A container for help information about a target type that can be used in a BUILD file."""
  pass


class BuildDictionaryInfoExtracter(object):
  """Extracts help information about the symbols that may be used in BUILD files."""

  basic_target_args = [
    FunctionArg('name', '', False, None),
    FunctionArg('dependencies', '', True, []),
    FunctionArg('description', '', True, None),
    FunctionArg('tags', '', True, None),
    FunctionArg('no_cache', '', True, False),
  ]

  @classmethod
  def get_description_from_docstring(cls, obj):
    doc = obj.__doc__ or ''
    p = doc.find('\n')
    if p == -1:
      return doc
    else:
      return doc[:p]

  @classmethod
  @memoized_method
  def _get_param_re(cls):
    return re.compile(':param\s+(\w+\s+)?(\w+):\s+(.*)')

  @classmethod
  def get_arg_descriptions_from_docstring(cls, obj):
    """Returns a map of arg name -> arg description found in :param: stanzas.

    Note that this does not handle multiline descriptions.  Descriptions of target params
    should be a single sentence on the first line, followed by more text, if any, on
    subsequent lines.
    """
    ret = {}
    doc = obj.__doc__ or ''
    lines = [s.strip() for s in doc.split('\n')]
    param_re = cls._get_param_re()
    for line in lines:
      m = param_re.match(line)
      if m:
        name, description = m.group(2, 3)
        ret[name] = description
    return ret

  @classmethod
  def get_target_args(cls, target_type):
    """Returns a list of FunctionArgs for the specified target_type."""
    return list(cls._get_target_args(target_type))

  @classmethod
  def _get_target_args(cls, target_type):
    # Target.__init__ has several args that are passed to it by TargetAddressable and not by
    # the BUILD file author, so we can't naively inspect it.  Instead we special-case its
    # true BUILD-file-facing arguments here.
    for arg in cls.basic_target_args:
      yield arg

    # Non-BUILD-file-facing Target.__init__ args that some Target subclasses capture in their
    # own __init__ for various reasons.
    ignore_args = set(['address', 'payload'])

    # Now look at the MRO, in reverse (so we see the more 'common' args first.
    methods_seen = set()  # Ensure we only look at each __init__ method once.
    for _type in reversed([t for t in target_type.mro()
                           if issubclass(t, Target) and not t == Target]):
      if inspect.ismethod(_type.__init__) and _type.__init__ not in methods_seen:
        for arg in cls._get_function_args(_type.__init__):
          if arg.name not in ignore_args:
            yield arg
        methods_seen.add(_type.__init__)

  @classmethod
  def get_function_args(cls, func):
    """Returns pairs (arg, default) for each argument of func, in declaration order.

    Ignores *args, **kwargs. Ignores self for methods.
    """
    return list(cls._get_function_args(func))

  @classmethod
  def _get_function_args(cls, func):
    arg_descriptions = cls.get_arg_descriptions_from_docstring(func)
    argspec = inspect.getargspec(func)
    arg_names = argspec.args
    if inspect.ismethod(func):
      arg_names = arg_names[1:]
    num_defaulted_args = len(argspec.defaults) if argspec.defaults is not None else 0
    first_defaulted_arg = len(arg_names) - num_defaulted_args
    for i in range(0, first_defaulted_arg):
      yield FunctionArg(arg_names[i], arg_descriptions.get(arg_names[i], ''), False, None)
    for i in range(first_defaulted_arg, len(arg_names)):
      yield FunctionArg(arg_names[i], arg_descriptions.get(arg_names[i], ''), True,
                        argspec.defaults[i - first_defaulted_arg])

  def __init__(self, buildfile_aliases):
    self._buildfile_aliases = buildfile_aliases

  def get_target_type_info(self):
    """Returns a sorted list of TargetTypeInfo for all known target types."""
    return sorted(self._get_target_type_info())

  def _get_target_type_info(self):
    for alias, target_type in self._buildfile_aliases.target_types.items():
      yield TargetTypeInfo(alias, self.get_description_from_docstring(target_type))
    for alias, target_macro_factory in self._buildfile_aliases.target_macro_factories.items():
      # Take the description from the first target type we encounter that has one.
      for target_type in target_macro_factory.target_types:
        description = self.get_description_from_docstring(target_type)
        if description:
          yield TargetTypeInfo(alias, description)
          break
