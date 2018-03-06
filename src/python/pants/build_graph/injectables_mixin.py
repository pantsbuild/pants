# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.address import Address


class InjectablesMixin(object):
  """A mixin for classes (typically optionables) that require certain targets in order to function.

  :API: public
  """
  class NoMappingForKey(Exception):
    """Thrown when a mapping doesn't exist for a given injectables key."""

  class TooManySpecsForKey(Exception):
    """Thrown when a mapping contains multiple specs when a singular spec is expected."""

  def injectables(self, build_graph):
    """Given a `BuildGraph`, inject any targets required for this object to function.

    This function will be called just before `Target` injection time. Any objects injected here
    should have a static spec path that will need to be emitted, pre-injection, by the
    `injectables_specs` classmethod for the purpose of dependency association for e.g. `changed`.

    :API: public
    """

  @property
  def injectables_spec_mapping(self):
    """A mapping of {key: spec} that is used for locating injectable specs.

    This should be overridden by subclasses who wish to define an injectables mapping.

    :API: public
    """
    return {}

  def injectables_specs_for_key(self, key):
    """Given a key, yield all relevant injectable spec addresses.

    :API: public
    """
    mapping = self.injectables_spec_mapping
    if key not in mapping:
      raise self.NoMappingForKey(key)
    specs = mapping[key]
    assert isinstance(specs, list), (
      'invalid `injectables_spec_mapping` on {!r} for key "{}". '
      'expected a `list` but instead found a `{}`: {}'
    ).format(self, key, type(specs), specs)
    return [Address.parse(s).spec for s in specs]

  def injectables_spec_for_key(self, key):
    """Given a key, yield a singular spec representing that key.

    :API: public
    """
    specs = self.injectables_specs_for_key(key)
    specs_len = len(specs)
    if specs_len == 0:
      return None
    if specs_len != 1:
      raise self.TooManySpecsForKey('injectables spec mapping for key included {} elements, '
                                    'expected 1'.format(specs_len))
    return specs[0]
