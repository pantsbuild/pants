# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from enum import Enum

from pants.util import enums


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
    self.assertEqual("woof", enums.match(EnumMatchTest.Test.dog, match_mapping))
    self.assertEqual("meow", enums.match(EnumMatchTest.Test.cat, match_mapping))
    self.assertEqual("oink", enums.match(EnumMatchTest.Test.pig, match_mapping))

  def test_inexhaustive_match(self) -> None:
    with self.assertRaises(enums.InexhaustiveMatchError):
      enums.match(EnumMatchTest.Test.pig, {
        EnumMatchTest.Test.pig: "oink",
      })

  def test_unrecognized_match(self) -> None:
    with self.assertRaises(enums.UnrecognizedMatchError):
      enums.match(EnumMatchTest.Test.pig, {  # type: ignore
        EnumMatchTest.Test.dog: "woof",
        EnumMatchTest.Test.cat: "meow",
        EnumMatchTest.Test.pig: "oink",
        "horse": "neigh",
      })
