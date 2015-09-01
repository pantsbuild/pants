# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
from abc import abstractmethod
from collections import namedtuple

from pants.base.build_file_type_factory import BuildFileTypeFactory


class Macro(BuildFileTypeFactory):
  """A context aware object factory responsible for instantiating a set of addressable types.

  The macro acts to expand arguments to its alias in a BUILD file into one or more addressable
  instances.
  """

  @classmethod
  def wrap(cls, context_aware_object_factory, *produced_types):
    """Wraps an existing context aware object factory into a macro.

    :param context_aware_object_factory: The existing context aware object factory.
    :param *produced_types: One or more addressable types the context aware object factory creates.
    """
    if not produced_types:
      raise ValueError('The given `context_aware_object_factory` {} must expand at least 1 '
                       'produced type; none were registered'.format(context_aware_object_factory))

    class Wrapper(cls):
      @property
      def produced_types(self):
        return produced_types

      def expand(self, *args, **kwargs):
        context_aware_object_factory(self._parse_context, *args, **kwargs)
    return Wrapper

  def __init__(self, parse_context):
    self._parse_context = parse_context

  def __call__(self, *args, **kwargs):
    self.expand(*args, **kwargs)

  @abstractmethod
  def expand(self, *args, **kwargs):
    """Expands the given BUILD file arguments in to one or more addressable instances."""


class BuildFileAliases(namedtuple('BuildFileAliases',
                                  ['targets',
                                   'objects',
                                   'context_aware_object_factories',
                                   'anonymous_targets'])):
  """A structure containing sets of symbols to be exposed in BUILD files.

  There are three types of symbols that can be directly exposed:

  - targets: These are Target subclasses.
  - objects: These are any python object, from constants to types.
  - context_aware_object_factories: These are object factories that are passed a ParseContext and
    produce one or more objects that use data from the context to enable some feature or utility;
    you might call them a BUILD file "macro" since they expand parameters to some final, "real"
    BUILD file object.  Common uses include creating objects that must be aware of the current
    BUILD file path or functions that need to be able to create targets or objects from within the
    BUILD file parse.

  Additionally, targets can be exposed only indirectly via macros.  To do so you register:

  - anonymous_targets: These are Target subclasses.

  An exposed macro you registered in context_aware_object_factories can then use
  `ParseContext.create_object` passing the target type as its "alias" to create targets on behalf
  of the BUILD file author.
  """

  @classmethod
  def create(cls,
             targets=None,
             objects=None,
             context_aware_object_factories=None,
             anonymous_targets=None):
    """A convenience constructor that can accept zero to all alias types."""
    def copy(orig, copy_type):
      return copy_type(orig) if orig else copy_type()
    return cls(copy(targets, dict),
               copy(objects, dict),
               copy(context_aware_object_factories, dict),
               copy(anonymous_targets, set))

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
    wrapper.__name__ = str(".".join(["curry_context",
                                     wrappee.__module__,
                                     wrappee.__name__]))
    return wrapper

  def merge(self, other):
    """Merges a set of build file aliases and returns a new set of aliases containing both.

    Any duplicate aliases from `other` will trump.

    :param other: The BuildFileAliases to merge in.
    :type other: :class:`BuildFileAliases`
    :returns: A new BuildFileAliases containing other's aliases merged into ours.
    :rtype: :class:`BuildFileAliases`
    """
    if not isinstance(other, BuildFileAliases):
      raise TypeError('Can only merge other BuildFileAliases, given {0}'.format(other))
    all_aliases = self._asdict()
    other_aliases = other._asdict()
    for alias_type, alias_map in all_aliases.items():
      alias_map.update(other_aliases[alias_type])
    return BuildFileAliases(**all_aliases)
