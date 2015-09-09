# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)


class ParseContext(object):
  """The build file context that context aware objects - aka BUILD macros - operate against."""

  def __init__(self, rel_path, type_aliases):
    self._rel_path = rel_path
    self._type_aliases = type_aliases

  def create_object(self, alias, *args, **kwargs):
    """Constructs the type with the given alias using the given args and kwargs.

    NB: aliases may be the alias' object type itself if that type is known.

    :param alias: Either the type alias or the type itself.
    :type alias: string|type
    :param *args: These pass through to the underlying callable object.
    :param **kwargs: These pass through to the underlying callable object.
    :returns: The created object.
    """
    object_type = self._type_aliases.get(alias)
    if object_type is None:
      raise KeyError('There is no type registered for alias {0}'.format(alias))
    return object_type(*args, **kwargs)

  @property
  def rel_path(self):
    """Relative path from the build root to the BUILD file the context aware object is called in.

    :rtype string
    """
    return self._rel_path
