# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import copy
import unittest

from pants.option.option_value_container import OptionValueContainer
from pants.option.ranked_value import Rank, RankedValue


class OptionValueContainerTest(unittest.TestCase):
    def test_unknown_values(self) -> None:
        o = OptionValueContainer()
        o.foo = RankedValue(Rank.HARDCODED, 1)
        self.assertEqual(1, o.foo)

        with self.assertRaises(AttributeError):
            o.bar

    def test_value_ranking(self) -> None:
        o = OptionValueContainer()
        o.foo = RankedValue(Rank.CONFIG, 11)
        self.assertEqual(11, o.foo)
        self.assertEqual(Rank.CONFIG, o.get_rank("foo"))
        o.foo = RankedValue(Rank.HARDCODED, 22)
        self.assertEqual(11, o.foo)
        self.assertEqual(Rank.CONFIG, o.get_rank("foo"))
        o.foo = RankedValue(Rank.ENVIRONMENT, 33)
        self.assertEqual(33, o.foo)
        self.assertEqual(Rank.ENVIRONMENT, o.get_rank("foo"))
        o.foo = RankedValue(Rank.FLAG, 44)
        self.assertEqual(44, o.foo)
        self.assertEqual(Rank.FLAG, o.get_rank("foo"))

    def test_is_flagged(self) -> None:
        o = OptionValueContainer()

        o.foo = RankedValue(Rank.NONE, 11)
        self.assertFalse(o.is_flagged("foo"))

        o.foo = RankedValue(Rank.CONFIG, 11)
        self.assertFalse(o.is_flagged("foo"))

        o.foo = RankedValue(Rank.ENVIRONMENT, 11)
        self.assertFalse(o.is_flagged("foo"))

        o.foo = RankedValue(Rank.FLAG, 11)
        self.assertTrue(o.is_flagged("foo"))

    def test_indexing(self) -> None:
        o = OptionValueContainer()
        o.foo = RankedValue(Rank.CONFIG, 1)
        self.assertEqual(1, o["foo"])

        self.assertEqual(1, o.get("foo"))
        self.assertEqual(1, o.get("foo", 2))
        self.assertIsNone(o.get("unknown"))
        self.assertEqual(2, o.get("unknown", 2))

        with self.assertRaises(AttributeError):
            o["bar"]

    def test_iterator(self) -> None:
        o = OptionValueContainer()
        o.a = RankedValue(Rank.FLAG, 3)
        o.b = RankedValue(Rank.FLAG, 2)
        o.c = RankedValue(Rank.FLAG, 1)
        names = list(iter(o))
        self.assertListEqual(["a", "b", "c"], names)

    def test_copy(self) -> None:
        # copy semantics can get hairy when overriding __setattr__/__getattr__, so we test them.
        o = OptionValueContainer()
        o.foo = RankedValue(Rank.FLAG, 1)
        o.bar = RankedValue(Rank.FLAG, {"a": 111})

        p = copy.copy(o)

        # Verify that the result is in fact a copy.
        self.assertEqual(1, p.foo)  # Has original attribute.
        o.baz = RankedValue(Rank.FLAG, 42)
        self.assertFalse(hasattr(p, "baz"))  # Does not have attribute added after the copy.

        # Verify that it's a shallow copy by modifying a referent in o and reading it in p.
        # TODO: add type hints to ranked_value.py and option_value_container.py so that this works.
        o.bar["b"] = 222  # type: ignore[index]
        self.assertEqual({"a": 111, "b": 222}, p.bar)

    def test_deepcopy(self) -> None:
        # copy semantics can get hairy when overriding __setattr__/__getattr__, so we test them.
        o = OptionValueContainer()
        o.foo = RankedValue(Rank.FLAG, 1)
        o.bar = RankedValue(Rank.FLAG, {"a": 111})

        p = copy.deepcopy(o)

        # Verify that the result is in fact a copy.
        self.assertEqual(1, p.foo)  # Has original attribute.
        o.baz = RankedValue(Rank.FLAG, 42)
        self.assertFalse(hasattr(p, "baz"))  # Does not have attribute added after the copy.

        # Verify that it's a deep copy by modifying a referent in o and reading it in p.
        # TODO: add type hints to ranked_value.py and option_value_container.py so that this works.
        o.bar["b"] = 222  # type: ignore[index]
        self.assertEqual({"a": 111}, p.bar)
