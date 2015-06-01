# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import inspect


def memoized(func):
  """Memoizes the results of a function call.

  Exactly one result is memoized for each unique combination of function arguments.

  Note that the memoization is not thread-safe and the result cache will grow without bound so care
  must be taken to only apply this decorator to functions with single threaded access and an
  expected reasonably small set of unique call parameters.
  """
  if not inspect.isfunction(func):
    raise ValueError('The @memoized decorator must be applied innermost of all decorators.')

  memoized_results = {}

  @functools.wraps(func)
  def memoize(*args, **kwargs):
    key = args
    if kwargs:
      key += tuple(sorted(kwargs.items()))
    if key in memoized_results:
      return memoized_results[key]
    result = func(*args, **kwargs)
    memoized_results[key] = result
    return result
  return memoize


def memoized_property(func):
  """A convenience wrapper for memoizing properties.

  Applied like so:

  >>> class Foo(object):
  ...   @memoized_property
  ...   def name(self):
  ...     pass

  Is equivalent to:

  >>> class Foo(object):
  ...   @property
  ...   @memoized
  ...   def name(self):
  ...     pass

  """
  return property(memoized(func))


def memoized_classmethod(func):
  """A convenience wrapper for memoizing class methods.

  Applied like so:

  >>> class Foo(object):
  ...   @memoized_classmethod
  ...   def utility(cls):
  ...     pass

  Is equivalent to:

  >>> class Foo(object):
  ...   @classmethod
  ...   @memoized
  ...   def utility(cls):
  ...     pass

  """
  return classmethod(memoized(func))


def memoized_staticmethod(func):
  """A convenience wrapper for memoizing static methods.

  Applied like so:

  >>> class Foo(object):
  ...   @memoized_staticmethod
  ...   def utility():
  ...     pass

  Is equivalent to:

  >>> class Foo(object):
  ...   @staticmethod
  ...   @memoized
  ...   def utility():
  ...     pass

  """
  return staticmethod(memoized(func))
