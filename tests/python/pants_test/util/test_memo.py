# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.util.memo import (
    memoized,
    memoized_classmethod,
    memoized_classproperty,
    memoized_method,
    memoized_property,
    memoized_staticmethod,
    memoized_staticproperty,
    per_instance,
    testable_memoized_property,
)


class MemoizeTest(unittest.TestCase):
    def test_function_application_positional(self):
        calculations = []

        @memoized
        def multiply(first, second):
            calculations.append((first, second))
            return first * second

        self.assertEqual(6, multiply(2, 3))
        self.assertEqual(6, multiply(3, 2))
        self.assertEqual(6, multiply(2, 3))

        self.assertEqual([(2, 3), (3, 2)], calculations)

    def test_function_application_kwargs(self):
        calculations = []

        @memoized()
        def multiply(first, second):
            calculations.append((first, second))
            return first * second

        self.assertEqual(6, multiply(first=2, second=3))
        self.assertEqual(6, multiply(second=3, first=2))
        self.assertEqual(6, multiply(first=2, second=3))

        self.assertEqual([(2, 3)], calculations)

    def test_function_application_mixed(self):
        calculations = []

        @memoized
        def func(*args, **kwargs):
            calculations.append((args, kwargs))
            return args, kwargs

        self.assertEqual((("a",), {"fred": 42, "jane": True}), func("a", fred=42, jane=True))
        self.assertEqual((("a", 42), {"jane": True}), func("a", 42, jane=True))
        self.assertEqual((("a",), {"fred": 42, "jane": True}), func("a", jane=True, fred=42))

        self.assertEqual(
            [(("a",), {"fred": 42, "jane": True}), (("a", 42), {"jane": True})], calculations
        )

    def test_function_application_potentially_ambiguous_parameters(self):
        calculations = []

        @memoized
        def func(*args, **kwargs):
            calculations.append((args, kwargs))
            return args, kwargs

        self.assertEqual(((("a", 42),), {}), func(("a", 42)))
        self.assertEqual(((), {"a": 42}), func(a=42))

        self.assertEqual([((("a", 42),), {}), ((), {"a": 42})], calculations)

    def test_key_factory(self):
        def create_key(num):
            return num % 2

        calculations = []

        @memoized(key_factory=create_key)
        def square(num):
            calculations.append(num)
            return num * num

        self.assertEqual(4, square(2))
        self.assertEqual(9, square(3))
        self.assertEqual(4, square(4))
        self.assertEqual(9, square(5))
        self.assertEqual(4, square(8))
        self.assertEqual(9, square(7))

        self.assertEqual([2, 3], calculations)

    def test_cache_factory(self):
        class SingleEntryMap(dict):
            def __setitem__(self, key, value):
                self.clear()
                return super().__setitem__(key, value)

        calculations = []

        @memoized(cache_factory=SingleEntryMap)
        def square(num):
            calculations.append(num)
            return num * num

        self.assertEqual(4, square(2))
        self.assertEqual(4, square(2))
        self.assertEqual(9, square(3))
        self.assertEqual(9, square(3))
        self.assertEqual(4, square(2))
        self.assertEqual(4, square(2))

        self.assertEqual([2, 3, 2], calculations)

    def test_forget(self):
        calculations = []

        @memoized
        def square(num):
            calculations.append(num)
            return num * num

        self.assertEqual(4, square(2))
        self.assertEqual(4, square(2))
        self.assertEqual(9, square(3))
        self.assertEqual(9, square(3))

        square.forget(2)

        self.assertEqual(4, square(2))
        self.assertEqual(4, square(2))
        self.assertEqual(9, square(3))
        self.assertEqual(9, square(3))

        self.assertEqual([2, 3, 2], calculations)

    def test_clear(self):
        calculations = []

        @memoized
        def square(num):
            calculations.append(num)
            return num * num

        self.assertEqual(4, square(2))
        self.assertEqual(4, square(2))
        self.assertEqual(9, square(3))
        self.assertEqual(9, square(3))

        square.clear()

        self.assertEqual(4, square(2))
        self.assertEqual(4, square(2))
        self.assertEqual(9, square(3))
        self.assertEqual(9, square(3))

        self.assertEqual([2, 3, 2, 3], calculations)

    class _Called(object):
        def __init__(self, increment):
            self._calls = 0
            self._increment = increment

        def _called(self):
            self._calls += self._increment
            return self._calls

    def test_instancemethod_application_id_eq(self):
        class Foo(self._Called):
            @memoized
            def calls(self):
                return self._called()

        foo1 = Foo(1)
        foo2 = Foo(2)

        # Different (`!=`) Foo instances have their own cache:
        self.assertEqual(1, foo1.calls())
        self.assertEqual(1, foo1.calls())

        self.assertEqual(2, foo2.calls())
        self.assertEqual(2, foo2.calls())

    def test_instancemethod_application_degenerate_eq(self):
        class Foo(self._Called):
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
        self.assertEqual(3, foo1.calls_per_eq())
        self.assertEqual(3, foo1.calls_per_eq())

        self.assertEqual(3, foo2.calls_per_eq())
        self.assertEqual(3, foo2.calls_per_eq())

        # Here the cache is split between the instances which is likely the expected behavior:
        self.assertEqual(6, foo1.calls_per_instance())
        self.assertEqual(6, foo1.calls_per_instance())

        self.assertEqual(4, foo2.calls_per_instance())
        self.assertEqual(4, foo2.calls_per_instance())

    def test_descriptor_application_invalid(self):
        with self.assertRaises(ValueError):
            # Can't decorate a descriptor
            class Foo:
                @memoized
                @property
                def name(self):
                    pass

    def test_memoized_method(self):
        class Foo:
            _x = "x0"

            @memoized_method
            def method(self, y):
                return self._x + y

        foo = Foo()
        self.assertEqual("x0y0", foo.method("y0"))
        Foo._x = "x1"
        self.assertEqual("x0y0", foo.method("y0"))
        # The (foo, 'y1') pair is the cache key, which is different than the previous (foo, 'y0'), so we
        # recalculate, and in the process read the new value of `Foo._x`.
        self.assertEqual("x1y1", foo.method("y1"))

    def test_memoized_class_methods(self):
        externally_scoped_value = "e0"

        class Foo:
            _x = "x0"

            @memoized_classmethod
            def class_method(cls, y):
                return cls._x + y

            @memoized_classproperty
            def class_property(cls):
                return cls._x

            @memoized_staticmethod
            def static_method(z):
                return externally_scoped_value + z

            @memoized_staticproperty
            def static_property():
                return externally_scoped_value

        self.assertEqual("x0", Foo.class_property)
        self.assertEqual("x0y0", Foo.class_method("y0"))
        self.assertEqual("e0", Foo.static_property)
        self.assertEqual("e0z0", Foo.static_method("z0"))

        Foo._x = "x1"
        # The property is cached.
        self.assertEqual("x0", Foo.class_property)
        # The method is cached for previously made calls only.
        self.assertEqual("x0y0", Foo.class_method("y0"))
        self.assertEqual("x1y1", Foo.class_method("y1"))

        externally_scoped_value = "e1"
        self.assertEqual("e0", Foo.static_property)
        self.assertEqual("e0z0", Foo.static_method("z0"))
        self.assertEqual("e1z1", Foo.static_method("z1"))

    def test_descriptor_application_valid(self):
        class Foo(self._Called):
            @property
            @memoized
            def calls(self):
                return self._called()

        foo1 = Foo(1)
        self.assertEqual(1, foo1.calls)
        self.assertEqual(1, foo1.calls)

        foo2 = Foo(2)
        self.assertEqual(2, foo2.calls)
        self.assertEqual(2, foo2.calls)

    def test_memoized_property(self):
        class Foo(self._Called):
            @memoized_property
            def calls(self):
                return self._called()

        foo1 = Foo(1)
        self.assertEqual(1, foo1.calls)
        self.assertEqual(1, foo1.calls)

        foo2 = Foo(2)
        self.assertEqual(2, foo2.calls)
        self.assertEqual(2, foo2.calls)

        with self.assertRaises(AttributeError):
            foo2.calls = None

    def test_mutable_memoized_property(self):
        class Foo(self._Called):
            @testable_memoized_property
            def calls(self):
                return self._called()

        foo1 = Foo(1)
        self.assertEqual(1, foo1.calls)
        self.assertEqual(1, foo1.calls)

        foo2 = Foo(2)
        self.assertEqual(2, foo2.calls)
        self.assertEqual(2, foo2.calls)

        foo2.calls = None
        self.assertIsNone(foo2.calls)

    def test_memoized_property_forget(self):
        class Foo(self._Called):
            @memoized_property
            def calls(self):
                return self._called()

        foo1 = Foo(1)

        # Forgetting before caching should be a harmless noop
        del foo1.calls

        self.assertEqual(1, foo1.calls)
        self.assertEqual(1, foo1.calls)

        foo2 = Foo(2)
        self.assertEqual(2, foo2.calls)
        self.assertEqual(2, foo2.calls)

        # Now un-cache foo2's calls result and observe no effect on foo1.calls, but a re-compute for
        # foo2.calls
        del foo2.calls

        self.assertEqual(1, foo1.calls)
        self.assertEqual(1, foo1.calls)

        self.assertEqual(4, foo2.calls)
        self.assertEqual(4, foo2.calls)
