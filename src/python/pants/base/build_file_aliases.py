# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import namedtuple

import functools


class BuildFileAliases(namedtuple('BuildFileAliases',
                                  ['targets', 'objects', 'context_aware_object_factories'])):
  """A structure containing set of symbols to be exposed in BUILD files.

  There are three types of symbols that can be exposed:

  - targets: These are Target subclasses.
  - objects: These are any python object, from constants to types.
  - context_aware_object_factories: These are object factories that are passed a ParseContext and
    produce some object that uses data from the context to enable some feature or utility.  Common
    uses include objects that must be aware of the current BUILD file path or functions that need
    to be able to create targets or objects from within the BUILD file parse.
  """

  @classmethod
  def create(cls, targets=None, objects=None, context_aware_object_factories=None):
    """A convenience constructor that can accept zero to all alias types."""
    def copy(orig):
      return orig.copy() if orig else {}
    return cls(copy(targets), copy(objects), copy(context_aware_object_factories))

  @classmethod
  def curry_context(cls, wrappee):
    """Curry a function with a build file context.

    Given a function foo(ctx, bar) that you want to expose in BUILD files
    as foo(bar), use::

        context_aware_object_factories={
          'foo': BuildFileAliases.curry_context(foo),
        }
    """
    # You might wonder: why not just use lambda and functools.partial?
    # That loses the __doc__, thus messing up the BUILD dictionary.
    wrapper = lambda ctx: functools.partial(wrappee, ctx)
    wrapper.__doc__ = wrappee.__doc__
    return wrapper

  def merge(self, other):
    """Merges a set of build file aliases and returns a new set of aliases containing both.

    Any duplicate aliases from `other` will trump.
    """
    if not isinstance(other, BuildFileAliases):
      raise TypeError('Can only merge other BuildFileAliases, given {0}'.format(other))
    all_aliases = self._asdict()
    other_aliases = other._asdict()
    for alias_type, alias_map in all_aliases.items():
      alias_map.update(other_aliases[alias_type])
    return BuildFileAliases(**all_aliases)
