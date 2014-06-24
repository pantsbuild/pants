# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple
from functools import partial
import inspect
import logging

from pants.base.build_file_aliases import BuildFileAliases

from pants.base.macro_context import MacroContext
from pants.base.target import Target
from pants.base.target_proxy import TargetCallProxy


logger = logging.getLogger(__name__)


class BuildConfiguration(object):
  """Stores the types and helper functions exposed to BUILD files as well as the commands and goals
  that can operate on the targets defined in them.
  """

  ParseContext = namedtuple('ParseContext', ['registered_target_proxies', 'parse_globals'])

  @staticmethod
  def _is_target_type(obj):
    return inspect.isclass(obj) and issubclass(obj, Target)

  def __init__(self):
    self._target_aliases = {}
    self._exposed_objects = {}
    self._exposed_macros = {}
    self._exposed_macro_factories = {}

  def registered_aliases(self):
    """Return the registered aliases exposed in BUILD files.

    This dict isn't so useful for actually parsing BUILD files.
    It's useful for generating things like
    http://pantsbuild.github.io/build_dictionary.html
    """
    return BuildFileAliases.create(
        targets=self._target_aliases,
        objects=self._exposed_objects,
        macros=self._exposed_macros)

  def register_aliases(self, aliases):
    """Registers the given aliases to be exposed in parsed BUILD files."""
    for alias, target_type in aliases.targets.items():
      self.register_target_alias(alias, target_type)

    for alias, obj in aliases.objects.items():
      self.register_exposed_object(alias, obj)

    for alias, macro in aliases.macros.items():
      self.register_exposed_macro(alias, macro)

  def register_target_alias(self, alias, target):
    """Registers the given target type under the given alias."""
    if not self._is_target_type(target):
      raise TypeError('Only Target types can be registered via `register_target_alias`, '
                      'given {0}'.format(target))

    if alias in self._target_aliases:
      logger.warn('Target alias {alias} has already been registered.  Overwriting!'
                  .format(alias=alias))
    self._target_aliases[alias] = target

  def register_exposed_object(self, alias, obj):
    """Registers the given object under the given alias.

    The object must not be a target subclass.  Those should be registered via
    `register_target_alias`.
    """
    if self._is_target_type(obj):
      raise TypeError('The exposed object {0} is a Target - these should be registered '
                      'via `register_target_alias`'.format(obj))

    if alias in self._exposed_objects:
      logger.warn('Object alias {alias} has already been registered.  Overwriting!'
                  .format(alias=alias))
    self._exposed_objects[alias] = obj

  def register_exposed_macro(self, alias, macro):
    """Registers the given macro under the given alias.

    Macros come in two forms, each of which must accept a `macro_context` argument in the last
    positional slot, as a defaulted arg or else via kwargs.

    In one form the macro is a class and its constructor must accept the `macro_context` argument.
    These macros types will be constructed before being injected into the BUILD file parse context
    under `alias`.

    In the other form the macro is a function or method.  These macros functions will have the
    `macro_context` argument curried and the resulting function exposed in the BUILD file parse
    context under `alias`
    """
    if self._is_target_type(macro):
      raise TypeError('The exposed macro {macro} is a Target - these should be registered '
                      'via `register_target_alias`'.format(macro=macro))

    if alias in self._exposed_macros:
      logger.warn('Macro alias {alias} has already been registered.  Overwriting!'
                  .format(alias=alias))

    def accepts_macro_context_arg(func, args_max=None):
      # We accept any function that takes an argument named `macro_context` in the last
      # non-defaulted argument position or else in any position if defaulted.  If there is no
      # explicit `macro_context` arg we accept functions taking keyword args.
      arg_spec = inspect.getargspec(func)
      if arg_spec.args and ('macro_context' in arg_spec.args):
        index = arg_spec.args.index('macro_context')
        num_args = len(arg_spec.args)
        if args_max and num_args > args_max:
          return False
        if index == (num_args - 1):
          return True
        if arg_spec.defaults and index >= (num_args - len(arg_spec.defaults) - 1):
          return True
      return arg_spec.keywords

    if inspect.isfunction(macro) or inspect.ismethod(macro):
      if accepts_macro_context_arg(macro):
        self._exposed_macro_factories[alias] = lambda ctx: partial(macro, macro_context=ctx)
        self._exposed_macros[alias] = macro
      else:
        raise TypeError('The given macro {macro} function does not accept a curried '
                        '`macro_context` argument'.format(macro=macro))
    elif inspect.isclass(macro):
      if accepts_macro_context_arg(macro.__init__, args_max=2):  # (self, macro_context)
        self._exposed_macro_factories[alias] = lambda ctx: macro(macro_context=ctx)
        self._exposed_macros[alias] = macro
      else:
        raise TypeError('The given macro {macro} cannot be constructed with a single '
                        '`macro_context` argument'.format(macro=macro))
    else:
      raise TypeError('The given macro {macro} must be a function, method or '
                      'class'.format(macro=macro))

  def create_parse_context(self, build_file):
    """Creates a fresh parse context for the given build file."""
    type_aliases = self._exposed_objects.copy()

    registered_target_proxies = set()
    for alias, target_type in self._target_aliases.items():
      target_call_proxy = TargetCallProxy(target_type=target_type,
                                          build_file=build_file,
                                          registered_target_proxies=registered_target_proxies)
      type_aliases[alias] = target_call_proxy

    macro_context = MacroContext(rel_path=build_file.spec_path, type_aliases=type_aliases)

    parse_globals = type_aliases.copy()

    # TODO(pl): Don't inject __file__ into the context.  BUILD files should not be aware
    # of their location on the filesystem.
    parse_globals['__file__'] = build_file.full_path

    for alias, macro_factory in self._exposed_macro_factories.items():
      parse_globals[alias] = macro_factory(macro_context)

    return self.ParseContext(registered_target_proxies, parse_globals)
