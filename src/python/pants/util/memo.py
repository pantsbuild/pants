# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import functools
import inspect
from contextlib import contextmanager
from typing import Any, Callable, Optional, TypeVar

from pants.util.meta import T, classproperty

FuncType = Callable[..., Any]
F = TypeVar("F", bound=FuncType)


# Used as a sentinel that disambiguates tuples passed in *args from coincidentally matching tuples
# formed from kwargs item pairs.
_kwargs_separator = (object(),)


def equal_args(*args, **kwargs):
    """A memoized key factory that compares the equality (`==`) of a stable sort of the
    parameters."""
    key = args
    if kwargs:
        key += _kwargs_separator + tuple(sorted(kwargs.items()))
    return key


class InstanceKey:
    """An equality wrapper for an arbitrary object instance.

    This wrapper leverages `id` and `is` for fast `__hash__` and `__eq__` but both of these rely on
    the object in question not being gc'd since both `id` and `is` rely on the instance address
    which can be recycled; so we retain a strong reference to the instance to ensure no recycling
    can occur.
    """

    def __init__(self, instance):
        self._instance = instance
        self._hash = id(instance)

    def __hash__(self):
        return self._hash

    def __eq__(self, other):
        if self._instance is other:
            return True
        if isinstance(other, InstanceKey):
            return self._instance is other._instance
        return False


def per_instance(*args, **kwargs):
    """A memoized key factory that works like `equal_args` except that the first parameter's
    identity is used when forming the key.

    This is a useful key factory when you want to enforce memoization happens per-instance for an
    instance method in a class hierarchy that defines a custom `__hash__`/`__eq__`.
    """
    instance_and_rest = (InstanceKey(args[0]),) + args[1:]
    return equal_args(*instance_and_rest, **kwargs)


def memoized(func: Optional[F] = None, key_factory=equal_args, cache_factory=dict) -> F:
    """Memoizes the results of a function call.

    By default, exactly one result is memoized for each unique combination of function arguments.

    Note that memoization is not thread-safe and the default result cache will grow without bound;
    so care must be taken to only apply this decorator to functions with single threaded access and
    an expected reasonably small set of unique call parameters.

    Note that the wrapped function comes equipped with 3 helper function attributes:

    + `put(*args, **kwargs)`: A context manager that takes the same arguments as the memoized
                              function and yields a setter function to set the value in the
                              memoization cache.
    + `forget(*args, **kwargs)`: Takes the same arguments as the memoized function and causes the
                                 memoization cache to forget the computed value, if any, for those
                                 arguments.
    + `clear()`: Causes the memoization cache to be fully cleared.

    :API: public

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
        return functools.partial(  # type: ignore[return-value]
            memoized, key_factory=key_factory, cache_factory=cache_factory
        )

    if not inspect.isfunction(func):
        raise ValueError("The @memoized decorator must be applied innermost of all decorators.")

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

    @contextmanager
    def put(*args, **kwargs):
        key = key_func(*args, **kwargs)
        yield functools.partial(memoized_results.__setitem__, key)

    memoize.put = put  # type: ignore[attr-defined]

    def forget(*args, **kwargs):
        key = key_func(*args, **kwargs)
        if key in memoized_results:
            del memoized_results[key]

    memoize.forget = forget  # type: ignore[attr-defined]

    def clear():
        memoized_results.clear()

    memoize.clear = clear  # type: ignore[attr-defined]

    return memoize  # type: ignore[return-value]


def memoized_method(func: Optional[F] = None, key_factory=per_instance, cache_factory=dict) -> F:
    """A convenience wrapper for memoizing instance methods.

    Typically you'd expect a memoized instance method to hold a cached value per class instance;
    however, for classes that implement a custom `__hash__`/`__eq__` that can hash separate instances
    the same, `@memoized` will share cached values across `==` class instances.  Using
    `@memoized_method` defaults to a `per_instance` key for the cache to provide the expected cached
    value per-instance behavior.

    Applied like so:

    >>> class Foo:
    ...   @memoized_method
    ...   def name(self):
    ...     pass

    Is equivalent to:

    >>> class Foo:
    ...   @memoized(key_factory=per_instance)
    ...   def name(self):
    ...     pass

    :API: public

    :param func: The function to wrap.  Only generally passed by the python runtime and should be
                 omitted when passing a custom `key_factory` or `cache_factory`.
    :param key_factory: A function that can form a cache key from the arguments passed to the
                        wrapped, memoized function; by default `per_instance`.
    :param kwargs: Any extra keyword args accepted by `memoized`.
    :raises: `ValueError` if the wrapper is applied to anything other than a function.
    :returns: A wrapped function that memoizes its results or else a function wrapper that does this.
    """
    return memoized(func=func, key_factory=key_factory, cache_factory=cache_factory)


def memoized_property(
    func: Optional[Callable[..., T]] = None, key_factory=per_instance, cache_factory=dict
) -> T:
    """A convenience wrapper for memoizing properties.

    Applied like so:

    >>> class Foo:
    ...   @memoized_property
    ...   def name(self):
    ...     pass

    Is equivalent to:

    >>> class Foo:
    ...   @property
    ...   @memoized_method
    ...   def name(self):
    ...     pass

    Which is equivalent to:

    >>> class Foo:
    ...   @property
    ...   @memoized(key_factory=per_instance)
    ...   def name(self):
    ...     pass

    By default a deleter for the property is setup that un-caches the property such that a subsequent
    property access re-computes the value.  In other words, for this `now` @memoized_property:

    >>> import time
    >>> class Bar:
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

    :API: public

    :param func: The property getter method to wrap.  Only generally passed by the python runtime and
                 should be omitted when passing a custom `key_factory` or `cache_factory`.
    :param key_factory: A function that can form a cache key from the arguments passed to the
                        wrapped, memoized function; by default `per_instance`.
    :param kwargs: Any extra keyword args accepted by `memoized`.
    :raises: `ValueError` if the wrapper is applied to anything other than a function.
    :returns: A read-only property that memoizes its calculated value and un-caches its value when
              `del`ed.
    """
    getter = memoized_method(func=func, key_factory=key_factory, cache_factory=cache_factory)
    return property(  # type: ignore[return-value]
        fget=getter,
        fdel=lambda self: getter.forget(self),  # type: ignore[attr-defined, no-any-return]
    )


# TODO[13244]: fix type hint issue when using @memoized_classmethod and friends
def memoized_classmethod(
    func: Optional[F] = None, key_factory=per_instance, cache_factory=dict
) -> F:
    return classmethod(  # type: ignore[return-value]
        memoized_method(func, key_factory=key_factory, cache_factory=cache_factory)
    )


def memoized_classproperty(
    func: Optional[Callable[..., T]] = None, key_factory=per_instance, cache_factory=dict
) -> T:
    return classproperty(
        memoized_classmethod(func, key_factory=key_factory, cache_factory=cache_factory)
    )


def testable_memoized_property(
    func: Optional[Callable[..., T]] = None, key_factory=per_instance, cache_factory=dict
) -> T:
    """A variant of `memoized_property` that allows for setting of properties (for tests, etc)."""
    getter = memoized_method(func=func, key_factory=key_factory, cache_factory=cache_factory)

    def setter(self, val):
        with getter.put(self) as putter:
            putter(val)

    return property(  # type: ignore[return-value]
        fget=getter,
        fset=setter,
        fdel=lambda self: getter.forget(self),  # type: ignore[attr-defined, no-any-return]
    )
