# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.util.memo import (
    memoized,
    memoized_classmethod,
    memoized_classproperty,
    memoized_method,
    memoized_property,
    per_instance,
    testable_memoized_property,
)


# TODO[13244]
def test_function_application_positional():
    calculations = []

    @memoized
    def multiply(first, second):
        calculations.append((first, second))
        return first * second

    assert 6 == multiply(2, 3)
    assert 6 == multiply(3, 2)
    assert 6 == multiply(2, 3)

    assert [(2, 3), (3, 2)] == calculations


# TODO[13244]
def test_function_application_kwargs():
    calculations = []

    @memoized()
    def multiply(first, second):
        calculations.append((first, second))
        return first * second

    assert 6 == multiply(first=2, second=3)
    assert 6 == multiply(second=3, first=2)
    assert 6 == multiply(first=2, second=3)

    assert [(2, 3)] == calculations


# TODO[13244]
def test_function_application_mixed():
    calculations = []

    @memoized
    def func(*args, **kwargs):
        calculations.append((args, kwargs))
        return args, kwargs

    assert (("a",), {"fred": 42, "jane": True}) == func("a", fred=42, jane=True)
    assert (("a", 42), {"jane": True}) == func("a", 42, jane=True)
    assert (("a",), {"fred": 42, "jane": True}) == func("a", jane=True, fred=42)

    assert [(("a",), {"fred": 42, "jane": True}), (("a", 42), {"jane": True})] == calculations


# TODO[13244]
def test_function_application_potentially_ambiguous_parameters():
    calculations = []

    @memoized
    def func(*args, **kwargs):
        calculations.append((args, kwargs))
        return args, kwargs

    assert ((("a", 42),), {}) == func(("a", 42))
    assert ((), {"a": 42}) == func(a=42)

    assert [((("a", 42),), {}), ((), {"a": 42})] == calculations


# TODO[13244]
def test_key_factory():
    def create_key(num):
        return num % 2

    calculations = []

    @memoized(key_factory=create_key)
    def square(num):
        calculations.append(num)
        return num * num

    assert 4 == square(2)
    assert 9 == square(3)
    assert 4 == square(4)
    assert 9 == square(5)
    assert 4 == square(8)
    assert 9 == square(7)

    assert [2, 3] == calculations


# TODO[13244]
def test_cache_factory():
    class SingleEntryMap(dict):
        def __setitem__(self, key, value):
            self.clear()
            return super().__setitem__(key, value)

    calculations = []

    @memoized(cache_factory=SingleEntryMap)
    def square(num):
        calculations.append(num)
        return num * num

    assert 4 == square(2)
    assert 4 == square(2)
    assert 9 == square(3)
    assert 9 == square(3)
    assert 4 == square(2)
    assert 4 == square(2)

    assert [2, 3, 2] == calculations


# TODO[13244]
def test_forget():
    calculations = []

    @memoized
    def square(num):
        calculations.append(num)
        return num * num

    assert 4 == square(2)
    assert 4 == square(2)
    assert 9 == square(3)
    assert 9 == square(3)

    square.forget(2)

    assert 4 == square(2)
    assert 4 == square(2)
    assert 9 == square(3)
    assert 9 == square(3)

    assert [2, 3, 2] == calculations


# TODO[13244]
def test_clear():
    calculations = []

    @memoized
    def square(num):
        calculations.append(num)
        return num * num

    assert 4 == square(2)
    assert 4 == square(2)
    assert 9 == square(3)
    assert 9 == square(3)

    square.clear()

    assert 4 == square(2)
    assert 4 == square(2)
    assert 9 == square(3)
    assert 9 == square(3)

    assert [2, 3, 2, 3] == calculations


class _Called:
    def __init__(self, increment):
        self._calls = 0
        self._increment = increment

    def _called(self):
        self._calls += self._increment
        return self._calls


# TODO[13244]
def test_instancemethod_application_id_eq():
    class Foo(_Called):
        @memoized
        def calls(self):
            return self._called()

    foo1 = Foo(1)
    foo2 = Foo(2)

    # Different (`!=`) Foo instances have their own cache:
    assert 1, foo1.calls()
    assert 1, foo1.calls()

    assert 2, foo2.calls()
    assert 2, foo2.calls()


# TODO[13244]
def test_instancemethod_application_degenerate_eq():
    class Foo(_Called):
        @memoized
        def calls_per_eq(self):
            return self._called()

        @memoized(key_factory=per_instance)
        def calls_per_instance(self):
            return self._called()

        def __hash__(self):
            return hash(type)

        def __eq__(self, other):
            return type(self) == type(other)

    foo1 = Foo(3)
    foo2 = Foo(4)

    # Here foo1 and foo2 share a cache since they are `==` which is likely surprising behavior:
    assert 3 == foo1.calls_per_eq()
    assert 3 == foo1.calls_per_eq()

    assert 3 == foo2.calls_per_eq()
    assert 3 == foo2.calls_per_eq()

    # Here the cache is split between the instances which is likely the expected behavior:
    assert 6 == foo1.calls_per_instance()
    assert 6 == foo1.calls_per_instance()

    assert 4 == foo2.calls_per_instance()
    assert 4 == foo2.calls_per_instance()


# TODO[13244]
def test_descriptor_application_invalid():
    with pytest.raises(ValueError):
        # Can't decorate a descriptor
        class Foo:
            @memoized
            @property
            def name(self):
                pass


# TODO[13244]
def test_memoized_method():
    class Foo:
        _x = "x0"

        @memoized_method
        def method(self, y):
            return self._x + y

    foo = Foo()
    assert "x0y0" == foo.method("y0")
    Foo._x = "x1"
    assert "x0y0" == foo.method("y0")
    # The (foo, 'y1') pair is the cache key, which is different than the previous (foo, 'y0'), so we
    # recalculate, and in the process read the new value of `Foo._x`.
    assert "x1y1" == foo.method("y1")


# TODO[13244]
#
# These tests are not type checked, due to missing `-> None` !!
# `def test_memoized_class_methods() -> None:` fails to:
#
# src/python/pants/util/memo_test.py:274:39: error: Argument 1 to "class_method" of "Foo" has
# incompatible type "str"; expected "Foo" [arg-type]
#        assert "x1y1" == Foo.class_method("y1")
#
# Would be good to also test that @memoized_classmethod() works.
def test_memoized_class_methods():
    class Foo:
        _x = "x0"

        @memoized_classmethod
        def class_method(cls, y):
            return cls._x + y

        @memoized_classproperty
        def class_property(cls):
            return cls._x

    assert "x0" == Foo.class_property
    assert "x0y0" == Foo.class_method("y0")

    Foo._x = "x1"
    # The property is cached.
    assert "x0" == Foo.class_property
    # The method is cached for previously made calls only.
    assert "x0y0" == Foo.class_method("y0")
    assert "x1y1" == Foo.class_method("y1")


# TODO[13244]
def test_descriptor_application_valid():
    class Foo(_Called):
        @property
        @memoized
        def calls(self):
            return self._called()

    foo1 = Foo(1)
    assert 1 == foo1.calls
    assert 1 == foo1.calls

    foo2 = Foo(2)
    assert 2 == foo2.calls
    assert 2 == foo2.calls


# TODO[13244]
def test_memoized_property():
    class Foo(_Called):
        @memoized_property
        def calls(self):
            return self._called()

    foo1 = Foo(1)
    assert 1 == foo1.calls
    assert 1 == foo1.calls

    foo2 = Foo(2)
    assert 2 == foo2.calls
    assert 2 == foo2.calls

    with pytest.raises(AttributeError):
        foo2.calls = None


# TODO[13244]
def test_mutable_memoized_property():
    class Foo(_Called):
        @testable_memoized_property
        def calls(self):
            return self._called()

    foo1 = Foo(1)
    assert 1 == foo1.calls
    assert 1 == foo1.calls

    foo2 = Foo(2)
    assert 2 == foo2.calls
    assert 2 == foo2.calls

    foo2.calls = None
    assert foo2.calls is None


# TODO[13244]
def test_memoized_property_forget():
    class Foo(_Called):
        @memoized_property
        def calls(self):
            return self._called()

    foo1 = Foo(1)

    # Forgetting before caching should be a harmless noop
    del foo1.calls

    assert 1 == foo1.calls
    assert 1 == foo1.calls

    foo2 = Foo(2)
    assert 2 == foo2.calls
    assert 2 == foo2.calls

    # Now un-cache foo2's calls result and observe no effect on foo1.calls, but a re-compute for
    # foo2.calls
    del foo2.calls

    assert 1 == foo1.calls
    assert 1 == foo1.calls

    assert 4 == foo2.calls
    assert 4 == foo2.calls
