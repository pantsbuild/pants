# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import inspect
import logging
from collections import namedtuple

from pants.base.addressable import AddressableCallProxy
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.layout import Layout, SourceRootLookup
from pants.base.parse_context import ParseContext
from pants.base.target import Target


logger = logging.getLogger(__name__)


class BuildConfiguration(object):
  """Stores the types and helper functions exposed to BUILD files as well as the commands and goals
  that can operate on the targets defined in them.
  """

  ParseState = namedtuple('ParseState', ['registered_addressable_instances', 'parse_globals'])

  @staticmethod
  def _is_target_type(obj):
    return inspect.isclass(obj) and issubclass(obj, Target)

  def __init__(self, layout=None):
    self._target_aliases = {}
    self._addressable_alias_map = {}
    self._exposed_objects = {}
    self._exposed_context_aware_object_factories = {}
    self.layout = layout or Layout()

  def registered_aliases(self):
    """Return the registered aliases exposed in BUILD files.

    This dict isn't so useful for actually parsing BUILD files.
    It's useful for generating things like
    http://pantsbuild.github.io/build_dictionary.html
    """
    return BuildFileAliases.create(
        targets=self._target_aliases,
        objects=self._exposed_objects,
        addressables=self._addressable_alias_map,
        context_aware_object_factories=self._exposed_context_aware_object_factories)

  def register_layout(self, layout):
    if not isinstance(layout, SourceRootLookup):
      raise TypeError("expected {} to be an instance of {}".format(layout, SourceRootLookup))

    self.layout.add_lookup(layout)

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
      logger.debug('Target alias {alias} has already been registered. Overwriting!'
                  .format(alias=alias))
    self._target_aliases[alias] = target
    self.register_addressable_alias(alias, target.get_addressable_type())

  def register_exposed_object(self, alias, obj):
    """Registers the given object under the given alias.

    The object must not be a target subclass.  Those should be registered via
    `register_target_alias`.
    """
    if self._is_target_type(obj):
      raise TypeError('The exposed object {0} is a Target - these should be registered '
                      'via `register_target_alias`'.format(obj))

    if alias in self._exposed_objects:
      logger.debug('Object alias {alias} has already been registered. Overwriting!'
                  .format(alias=alias))
    self._exposed_objects[alias] = obj

  def register_addressable_alias(self, alias, addressable_type):
    """Registers a general Addressable type under the given alias.

    Addressables are the general mechanism for capturing the name and value of objects instantiated
    in BUILD files.  Most notably, TargetAddressable is a subclass of Addressable, and
    `register_target_alias` delegates to this method after noting the alias mapping for
    other purposes.

    Any Addressable with the appropriate `addressable_name` implementation which is registered
    here and instantiated in a BUILD file will be accessible from the AddressMapper, regardless
    of the type of instance it yields.
    """
    if alias in self._addressable_alias_map:
      logger.debug('Addressable alias {alias} has already been registered. Overwriting!'
                  .format(alias=alias))
    self._addressable_alias_map[alias] = addressable_type

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
      logger.debug('This context aware object factory alias {alias} has already been registered. '
                  'Overwriting!'.format(alias=alias))

    if callable(context_aware_object_factory):
      self._exposed_context_aware_object_factories[alias] = context_aware_object_factory
    else:
      raise TypeError('The given context aware object factory {factory} must be a callable.'
                      .format(factory=context_aware_object_factory))

  def initialize_parse_state(self, build_file):
    """Creates a fresh parse state for the given build file."""
    type_aliases = self._exposed_objects.copy()

    registered_addressable_instances = []
    def registration_callback(address, addressable):
      registered_addressable_instances.append((address, addressable))

    source_root_for_current_build_file = self.layout.find_source_root_by_path(build_file.spec_path)
    for alias, addressable_type in self._addressable_alias_map.items():
      call_proxy = AddressableCallProxy(addressable_type=addressable_type,
                                        build_file=build_file,
                                        registration_callback=registration_callback,
                                        source_root=source_root_for_current_build_file)
      type_aliases[alias] = call_proxy

    parse_context = ParseContext(rel_path=build_file.spec_path, type_aliases=type_aliases)

    parse_globals = type_aliases.copy()
    for alias, object_factory in self._exposed_context_aware_object_factories.items():
      parse_globals[alias] = object_factory(parse_context)

    return self.ParseState(registered_addressable_instances, parse_globals)
