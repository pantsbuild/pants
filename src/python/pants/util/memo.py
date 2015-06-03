# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import inspect


# Used as a sentinel that disambiguates tuples passed in *args from coincidentally matching tuples
# formed from kwargs item pairs.
_kwargs_separator = (object(),)


def equal_args(*args, **kwargs):
  """A memoized key factory that compares the equality (`==`) of a stable sort of the parameters."""
  key = args
  if kwargs:
    key += _kwargs_separator + tuple(sorted(kwargs.items()))
  return key


def per_instance(*args, **kwargs):
  """A memoized key factory that works like `equal_args` except that the first parameter's identity
  is used when forming the key.

  This is a useful key factory when you want to enforce memoization happens per-instance for an
  instance method in a class hierarchy that defines a custom `__hash__`/`__eq__`.
  """
  # For methods, the cache should be per-instance, so we take the id of the self/cls argument
  # instead of relying on `==` since different instances may evaluate as `==`.  Additionally, we
  # pair the id with the instance to ensure the instance is not GC'd since `id` allows for re-use
  # of ids under GC.
  instance = args[0]
  unique_retained_instance = (id(instance), instance)

  instance_and_rest = (unique_retained_instance,) + args[1:]
  return equal_args(*instance_and_rest, **kwargs)


def memoized(func=None, key_factory=equal_args, cache_factory=dict):
  """Memoizes the results of a function call.

  By default, exactly one result is memoized for each unique combination of function arguments.

  Note that memoization is not thread-safe and the default result cache will grow without bound;
  so care must be taken to only apply this decorator to functions with single threaded access and
  an expected reasonably small set of unique call parameters.

  Note that the wrapped function comes equipped with 2 helper function attributes:

  + `forget(*args, **kwargs)`: Takes the same arguments as the memoized function and causes the
                               memoization cache to forget the computed value, if any, for those
                               arguments.
  + `clear()`: Causes the memoization cache to be fully cleared.

  :param func: The function to wrap.  Only generally passed by the python runtime and should be
               omitted when passing a custom `key_factory` or `cache_factory`.
  :param key_factory: A function that can form a cache key from the arguments passed to the
                      wrapped, memoized function; by default uses simple parameter-set equality;
                      ie `equal_args`.
  :param cache_factory: A no-arg callable that produces a mapping object to use for the memoized
                        method's value cache.  By default the `dict` constructor, but could be a
                        a factory for an LRU cache for example.
  :raises: `ValueError` if the wrapper is applied to anything other than a function.
  :returns: A wrapped function that memoizes its results or else a function wrapper that does this.
  """
  if func is None:
    # We're being applied as a decorator factory; ie: the user has supplied args, like so:
    # >>> @memoized(cache_factory=lru_cache)
    # ... def expensive_operation(user):
    # ...   pass
    # So we return a decorator with the user-supplied args curried in for the python decorator
    # machinery to use to wrap the upcoming func.
    #
    # NB: This is just a tricky way to allow for both `@memoized` and `@memoized(...params...)`
    # application forms.  Without this trick, ie: using a decorator class or nested decorator
    # function, the no-params application would have to be `@memoized()`.  It still can, but need
    # not be and a bare `@memoized` will work as well as a `@memoized()`.
    return functools.partial(memoized, key_factory=key_factory, cache_factory=cache_factory)

  if not inspect.isfunction(func):
    raise ValueError('The @memoized decorator must be applied innermost of all decorators.')

  key_func = key_factory or equal_args
  memoized_results = cache_factory() if cache_factory else {}

  @functools.wraps(func)
  def memoize(*args, **kwargs):
    key = key_func(*args, **kwargs)
    if key in memoized_results:
      return memoized_results[key]
    result = func(*args, **kwargs)
    memoized_results[key] = result
    return result

  def forget(*args, **kwargs):
    key = key_func(*args, **kwargs)
    if key in memoized_results:
      del memoized_results[key]
  memoize.forget = forget

  def clear():
    memoized_results.clear()
  memoize.clear = clear

  return memoize


def memoized_method(func=None, key_factory=per_instance, **kwargs):
  """A convenience wrapper for memoizing instance methods.

  Typically you'd expect a memoized instance method to hold a cached value per class instance;
  however, for classes that implement a custom `__hash__`/`__eq__` that can hash separate instances
  the same, `@memoized` will share cached values across `==` class instances.  Using
  `@memoized_method` defaults to a `per_instance` key for the cache to provide the expected cached
  value per-instance behavior.

  Applied like so:

  >>> class Foo(object):
  ...   @memoized_method
  ...   def name(self):
  ...     pass

  Is equivalent to:

  >>> class Foo(object):
  ...   @memoized(key_factory=per_instance)
  ...   def name(self):
  ...     pass

  :param func: The function to wrap.  Only generally passed by the python runtime and should be
               omitted when passing a custom `key_factory` or `cache_factory`.
  :param key_factory: A function that can form a cache key from the arguments passed to the
                      wrapped, memoized function; by default `per_instance`.
  :param kwargs: Any extra keyword args accepted by `memoized`.
  :raises: `ValueError` if the wrapper is applied to anything other than a function.
  :returns: A wrapped function that memoizes its results or else a function wrapper that does this.
  """
  return memoized(func=func, key_factory=key_factory, **kwargs)


def memoized_property(func=None, key_factory=per_instance, **kwargs):
  """A convenience wrapper for memoizing properties.

  Applied like so:

  >>> class Foo(object):
  ...   @memoized_property
  ...   def name(self):
  ...     pass

  Is equivalent to:

  >>> class Foo(object):
  ...   @property
  ...   @memoized_method
  ...   def name(self):
  ...     pass

  Which is equivalent to:

  >>> class Foo(object):
  ...   @property
  ...   @memoized(key_factory=per_instance)
  ...   def name(self):
  ...     pass

  By default a deleter for the property is setup that un-caches the property such that a subsequent
  property access re-computes the value.  In other words, for this `now` @memoized_property:

  >>> import time
  >>> class Bar(object):
  ...   @memoized_property
  ...   def now(self):
  ...     return time.time()

  You could write code like so:

  >>> bar = Bar()
  >>> bar.now
  1433267312.622095
  >>> time.sleep(5)
  >>> bar.now
  1433267312.622095
  >>> del bar.now
  >>> bar.now
  1433267424.056189
  >>> time.sleep(5)
  >>> bar.now
  1433267424.056189
  >>>

  :param func: The property getter method to wrap.  Only generally passed by the python runtime and
               should be omitted when passing a custom `key_factory` or `cache_factory`.
  :param key_factory: A function that can form a cache key from the arguments passed to the
                      wrapped, memoized function; by default `per_instance`.
  :param kwargs: Any extra keyword args accepted by `memoized`.
  :raises: `ValueError` if the wrapper is applied to anything other than a function.
  :returns: A read-only property that memoizes its calculated value and un-caches its value when
            `del`ed.
  """
  getter = memoized_method(func=func, key_factory=key_factory, **kwargs)
  return property(fget=getter, fdel=lambda self: getter.forget(self))
