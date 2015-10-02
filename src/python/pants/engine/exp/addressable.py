# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six


class AddressError(Exception):
  """Indicates an error assigning or resolving an address."""


class Addressed(object):
  """Describes an addressed item of a given type."""

  def __init__(self, addressed_type, address):
    self._addressed_type = addressed_type
    self._address = address

  @property
  def addressed_type(self):
    return self._addressed_type

  @property
  def address(self):
    return self._address

  def __repr__(self):
    return 'Addressed(addressed_type={!r}, address={!r})'.format(self._addressed_type,
                                                                 self._address)


def addressable(addressed_types, value):
  """Marks a value as accepting a given type, possibly lazily resolved via address."""
  if value is None:
    return None
  elif isinstance(value, addressed_types):
    return value
  elif isinstance(value, Addressed) and value.addressed_type == addressed_types:
    return value
  elif isinstance(value, six.string_types):
    return Addressed(addressed_types, value)
  else:
    raise AddressError('The given value is not an address or an {!r}: {!r}'
                       .format(addressed_types, value))


def addressables(addressed_types, values):
  """Marks a list as containing a given type, some elements of which are resolved via address."""
  # TODO(John Sirois): Instead of re-traversing all lists later to hydrate any potentially contained
  # Addressed objects, this could return a (marker) type.  The hydration could then avoid deep
  # introspection and just look for a - say - `Resolvable` value, and only resolve those.  Only if
  # perf is being tweaked might this need to be addressed.
  return [addressable(addressed_types, v) for v in values] if values else []


def addressable_mapping(addressed_types, mapping):
  """Marks a dict as containing values of a given type, some elements of which are resolved."""
  return {k: addressable(addressed_types, v) for k, v in mapping.items()} if mapping else {}
