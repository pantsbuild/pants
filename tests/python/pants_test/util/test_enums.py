# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from enum import Enum

from pants.util.enums import InexhaustiveMatchError, UnrecognizedMatchError, match


class EnumMatchTest(unittest.TestCase):
    class Test(Enum):
        dog = 0
        cat = 1
        pig = 2

    def test_valid_match(self) -> None:
        match_mapping = {
            EnumMatchTest.Test.dog: "woof",
            EnumMatchTest.Test.cat: "meow",
            EnumMatchTest.Test.pig: "oink",
        }
        self.assertEqual("woof", match(EnumMatchTest.Test.dog, match_mapping))
        self.assertEqual("meow", match(EnumMatchTest.Test.cat, match_mapping))
        self.assertEqual("oink", match(EnumMatchTest.Test.pig, match_mapping))

    def test_inexhaustive_match(self) -> None:
        with self.assertRaises(InexhaustiveMatchError):
            match(EnumMatchTest.Test.pig, {EnumMatchTest.Test.pig: "oink"})

    def test_unrecognized_match(self) -> None:
        with self.assertRaises(UnrecognizedMatchError):
            match(  # type: ignore[type-var]
                EnumMatchTest.Test.pig,
                {
                    EnumMatchTest.Test.dog: "woof",
                    EnumMatchTest.Test.cat: "meow",
                    EnumMatchTest.Test.pig: "oink",
                    "horse": "neigh",
                },
            )
