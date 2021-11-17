# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum

import pytest

from pants.util.enums import InexhaustiveMatchError, UnrecognizedMatchError, match


class TestEnumMatch:
    class Test(Enum):
        dog = 0
        cat = 1
        pig = 2

    def test_valid_match(self) -> None:
        match_mapping = {
            TestEnumMatch.Test.dog: "woof",
            TestEnumMatch.Test.cat: "meow",
            TestEnumMatch.Test.pig: "oink",
        }
        assert "woof" == match(TestEnumMatch.Test.dog, match_mapping)
        assert "meow" == match(TestEnumMatch.Test.cat, match_mapping)
        assert "oink" == match(TestEnumMatch.Test.pig, match_mapping)

    def test_inexhaustive_match(self) -> None:
        with pytest.raises(InexhaustiveMatchError):
            match(TestEnumMatch.Test.pig, {TestEnumMatch.Test.pig: "oink"})

    def test_unrecognized_match(self) -> None:
        with pytest.raises(UnrecognizedMatchError):
            match(  # type: ignore[type-var]
                TestEnumMatch.Test.pig,
                {
                    TestEnumMatch.Test.dog: "woof",
                    TestEnumMatch.Test.cat: "meow",
                    TestEnumMatch.Test.pig: "oink",
                    "horse": "neigh",
                },
            )
