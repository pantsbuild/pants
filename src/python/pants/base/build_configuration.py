# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple
import inspect
import logging

from pants.base.build_file_aliases import BuildFileAliases

from pants.base.parse_context import ParseContext
from pants.base.target import Target
from pants.base.target_proxy import TargetCallProxy


logger = logging.getLogger(__name__)


class BuildConfiguration(object):
  """Stores the types and helper functions exposed to BUILD files as well as the commands and goals
  that can operate on the targets defined in them.
  """

  ParseState = namedtuple('ParseState', ['registered_target_proxies', 'parse_globals'])

  @staticmethod
  def _is_target_type(obj):
    return inspect.isclass(obj) and issubclass(obj, Target)

  def __init__(self):
    self._target_aliases = {}
    self._exposed_objects = {}
    self._exposed_context_aware_object_factories = {}

  def registered_aliases(self):
    """Return the registered aliases exposed in BUILD files.

    This dict isn't so useful for actually parsing BUILD files.
    It's useful for generating things like
    http://pantsbuild.github.io/build_dictionary.html
    """
    return BuildFileAliases.create(
        targets=self._target_aliases,
        objects=self._exposed_objects,
        context_aware_object_factories=self._exposed_context_aware_object_factories)

  def register_aliases(self, aliases):
    """Registers the given aliases to be exposed in parsed BUILD files."""
    for alias, target_type in aliases.targets.items():
      self.register_target_alias(alias, target_type)

    for alias, obj in aliases.objects.items():
      self.register_exposed_object(alias, obj)

    for alias, context_aware_object_factory in aliases.context_aware_object_factories.items():
      self.register_exposed_context_aware_object_factory(alias, context_aware_object_factory)

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

  def register_exposed_context_aware_object_factory(self, alias, context_aware_object_factory):
    """Registers the given context aware object factory under the given alias.

    Context aware object factories must be callables that take a single ParseContext argument
    and return some object that will be exposed in the BUILD file parse context under `alias`.
    """
    if self._is_target_type(context_aware_object_factory):
      raise TypeError('The exposed context aware object factory {factory} is a Target - these '
                      'should be registered via `register_target_alias`'
                      .format(factory=context_aware_object_factory))

    if alias in self._exposed_context_aware_object_factories:
      logger.warn('This context aware object factory alias {alias} has already been registered. '
                  'Overwriting!'.format(alias=alias))

    if callable(context_aware_object_factory):
      self._exposed_context_aware_object_factories[alias] = context_aware_object_factory
    else:
      raise TypeError('The given context aware object factory {factory} must be a callable.'
                      .format(factory=context_aware_object_factory))

  def initialize_parse_state(self, build_file):
    """Creates a fresh parse state for the given build file."""
    type_aliases = self._exposed_objects.copy()

    registered_target_proxies = set()
    for alias, target_type in self._target_aliases.items():
      target_call_proxy = TargetCallProxy(target_type=target_type,
                                          build_file=build_file,
                                          registered_target_proxies=registered_target_proxies)
      type_aliases[alias] = target_call_proxy

    parse_context = ParseContext(rel_path=build_file.spec_path, type_aliases=type_aliases)

    parse_globals = type_aliases.copy()

    # TODO(pl): Don't inject __file__ into the context.  BUILD files should not be aware
    # of their location on the filesystem.
    parse_globals['__file__'] = build_file.full_path

    for alias, context_aware_object_factory in self._exposed_context_aware_object_factories.items():
      parse_globals[alias] = context_aware_object_factory(parse_context)

    return self.ParseState(registered_target_proxies, parse_globals)
