# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest

from pants.option.option_value_container import OptionValueContainerBuilder
from pants.option.ranked_value import Rank, RankedValue


class OptionValueContainerTest(unittest.TestCase):
    def test_unknown_values(self) -> None:
        ob = OptionValueContainerBuilder()
        ob.foo = RankedValue(Rank.HARDCODED, 1)
        o = ob.build()
        self.assertEqual(1, o.foo)

        with self.assertRaises(AttributeError):
            o.bar

    def test_value_ranking(self) -> None:
        ob = OptionValueContainerBuilder()
        ob.foo = RankedValue(Rank.CONFIG, 11)
        o = ob.build()
        self.assertEqual(11, o.foo)
        self.assertEqual(Rank.CONFIG, o.get_rank("foo"))
        ob.foo = RankedValue(Rank.HARDCODED, 22)
        o = ob.build()
        self.assertEqual(11, o.foo)
        self.assertEqual(Rank.CONFIG, o.get_rank("foo"))
        ob.foo = RankedValue(Rank.ENVIRONMENT, 33)
        o = ob.build()
        self.assertEqual(33, o.foo)
        self.assertEqual(Rank.ENVIRONMENT, o.get_rank("foo"))
        ob.foo = RankedValue(Rank.FLAG, 44)
        o = ob.build()
        self.assertEqual(44, o.foo)
        self.assertEqual(Rank.FLAG, o.get_rank("foo"))

    def test_is_flagged(self) -> None:
        ob = OptionValueContainerBuilder()

        ob.foo = RankedValue(Rank.NONE, 11)
        self.assertFalse(ob.build().is_flagged("foo"))

        ob.foo = RankedValue(Rank.CONFIG, 11)
        self.assertFalse(ob.build().is_flagged("foo"))

        ob.foo = RankedValue(Rank.ENVIRONMENT, 11)
        self.assertFalse(ob.build().is_flagged("foo"))

        ob.foo = RankedValue(Rank.FLAG, 11)
        self.assertTrue(ob.build().is_flagged("foo"))

    def test_indexing(self) -> None:
        ob = OptionValueContainerBuilder()
        ob.foo = RankedValue(Rank.CONFIG, 1)
        o = ob.build()

        self.assertEqual(1, o["foo"])
        self.assertEqual(1, o.get("foo"))
        self.assertEqual(1, o.get("foo", 2))
        self.assertIsNone(o.get("unknown"))
        self.assertEqual(2, o.get("unknown", 2))

        with self.assertRaises(AttributeError):
            o["bar"]

    def test_iterator(self) -> None:
        ob = OptionValueContainerBuilder()
        ob.a = RankedValue(Rank.FLAG, 3)
        ob.b = RankedValue(Rank.FLAG, 2)
        ob.c = RankedValue(Rank.FLAG, 1)
        o = ob.build()

        names = list(iter(o))
        self.assertListEqual(["a", "b", "c"], names)

    def test_copy(self) -> None:
        # copy semantics can get hairy when overriding __setattr__/__getattr__, so we test them.
        ob = OptionValueContainerBuilder()
        ob.foo = RankedValue(Rank.FLAG, 1)
        ob.bar = RankedValue(Rank.FLAG, {"a": 111})

        p = ob.build()
        z = ob.build()

        # Verify that the result is in fact a copy.
        self.assertEqual(1, p.foo)  # Has original attribute.
        ob.baz = RankedValue(Rank.FLAG, 42)
        self.assertFalse(hasattr(p, "baz"))  # Does not have attribute added after the copy.

        # Verify that it's a shallow copy by modifying a referent in o and reading it in p.
        p.bar["b"] = 222
        self.assertEqual({"a": 111, "b": 222}, z.bar)
