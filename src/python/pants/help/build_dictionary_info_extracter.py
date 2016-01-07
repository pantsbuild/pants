# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import inspect
import re
from collections import OrderedDict, namedtuple

from pants.base.exceptions import TaskError
from pants.build_graph.target import Target
from pants.util.memo import memoized_method


class FunctionArg(namedtuple('_FunctionArg', ['name', 'description', 'has_default', 'default'])):
  """An argument to a function."""
  pass


class BuildSymbolInfo(namedtuple('_BuildSymbolInfo', ['symbol', 'description', 'args'])):
  """A container for help information about a symbol that can be used in a BUILD file."""
  pass


class BuildDictionaryInfoExtracter(object):
  """Extracts help information about the symbols that may be used in BUILD files."""

  ADD_DESCR = '<Add description>'

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
  @memoized_method
  def _get_default_value_re(cls):
    return re.compile(' \([Dd]efault: (.*)\)')

  @classmethod
  def get_arg_descriptions_from_docstring(cls, obj):
    """Returns an ordered map of arg name -> arg description found in :param: stanzas.

    Note that this does not handle multiline descriptions.  Descriptions of target params
    should be a single sentence on the first line, followed by more text, if any, on
    subsequent lines.
    """
    ret = OrderedDict()
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
  def get_args_for_target_type(cls, target_type):
    return list(cls._get_args_for_target_type(target_type))

  @classmethod
  def _get_args_for_target_type(cls, target_type):
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
    for _type in reversed([t for t in target_type.mro() if issubclass(t, Target)]):
      if (inspect.ismethod(_type.__init__) and
          _type.__init__ not in methods_seen and
          _type.__init__ != Target.__init__):
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
      yield FunctionArg(arg_names[i], arg_descriptions.pop(arg_names[i], ''), False, None)
    for i in range(first_defaulted_arg, len(arg_names)):
      yield FunctionArg(arg_names[i], arg_descriptions.pop(arg_names[i], ''), True,
                        argspec.defaults[i - first_defaulted_arg])
    if argspec.varargs:
      yield FunctionArg('*{}'.format(argspec.varargs), arg_descriptions.pop(argspec.varargs, None),
                        False, None)

    if argspec.keywords:
      # Any remaining arg_descriptions are for kwargs.
      for arg_name, descr in arg_descriptions.items():
        # Get the default value out of the description, if present.
        mo = cls._get_default_value_re().search(descr)
        default_value = mo.group(1) if mo else None
        descr_sans_default = '{}{}'.format(descr[:mo.start()], descr[mo.end():]) if mo else descr
        yield FunctionArg(arg_name, descr_sans_default, True, default_value)

  def __init__(self, buildfile_aliases):
    self._buildfile_aliases = buildfile_aliases

  def get_target_args(self, alias):
    """Returns a list of FunctionArgs for the specified target_type."""
    target_types = list(self._buildfile_aliases.target_types_by_alias.get(alias))
    if not target_types:
      raise TaskError('No such target type: {}'.format(alias))
    return self.get_args_for_target_type(target_types[0])

  def get_object_args(self, alias):
    obj_type = self._buildfile_aliases.objects.get(alias)
    if not obj_type:
      raise TaskError('No such object type: {}'.format(alias))
    if inspect.isfunction(obj_type) or inspect.ismethod(obj_type):
      return self.get_function_args(obj_type)
    elif inspect.isclass(obj_type):
      return self.get_function_args(obj_type.__init__)
    elif hasattr(obj_type, '__call__'):
      return self.get_function_args(obj_type.__call__)
    else:
      return []

  def get_object_factory_args(self, alias):
    obj_factory = self._buildfile_aliases.context_aware_object_factories.get(alias)
    if not obj_factory:
      raise TaskError('No such context aware object factory: {}'.format(alias))
    return self.get_function_args(obj_factory.__call__)

  def get_target_type_info(self):
    """Returns a sorted list of BuildSymbolInfo for all known target types."""
    return sorted(self._get_target_type_info())

  def _get_target_type_info(self):
    for alias, target_type in self._buildfile_aliases.target_types.items():
      yield BuildSymbolInfo(alias,
                            self.get_description_from_docstring(target_type) or self.ADD_DESCR,
                            self.get_target_args(alias))
    for alias, target_macro_factory in self._buildfile_aliases.target_macro_factories.items():
      # Take the description from the first target type we encounter that has one.
      target_args = self.get_target_args(alias)
      for target_type in target_macro_factory.target_types:
        description = self.get_description_from_docstring(target_type)
        if description:
          yield BuildSymbolInfo(alias, description, target_args)
          break
      else:
        yield BuildSymbolInfo(alias, self.ADD_DESCR, target_args)

  def get_object_info(self):
    return sorted(self._get_object_info())

  def _get_object_info(self):
    for alias, obj in self._buildfile_aliases.objects.items():
      yield BuildSymbolInfo(alias,
                            self.get_description_from_docstring(obj) or self.ADD_DESCR,
                            self.get_object_args(alias))

  def get_object_factory_info(self):
    return sorted(self._get_object_factory_info())

  def _get_object_factory_info(self):
    for alias, factory_type in self._buildfile_aliases.context_aware_object_factories.items():
      yield BuildSymbolInfo(alias,
                            self.get_description_from_docstring(factory_type) or self.ADD_DESCR,
                            self.get_object_factory_args(alias))
