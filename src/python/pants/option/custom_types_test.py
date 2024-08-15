# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from datetime import timedelta
from textwrap import dedent
from typing import Dict, List, Union

import pytest

from pants.option.custom_types import (
    DictValueComponent,
    ListValueComponent,
    UnsetBool,
    _flatten_shlexed_list,
    duration,
    memory_size,
)
from pants.option.errors import ParseError

ValidPrimitives = Union[int, str]
ParsedList = List[ValidPrimitives]
ParsedDict = Dict[str, Union[ValidPrimitives, ParsedList]]


def test_memory_size() -> None:
    assert memory_size("1GiB") == 1_073_741_824
    assert memory_size(" 1  GiB ") == 1_073_741_824
    assert memory_size("1.22GiB") == 1_309_965_025

    assert memory_size("1MiB") == 1_048_576
    assert memory_size(" 1  MiB ") == 1_048_576
    assert memory_size("1.4MiB") == 1_468_006

    assert memory_size("1KiB") == 1024
    assert memory_size(" 1  KiB ") == 1024
    assert memory_size("1.4KiB") == 1433

    assert memory_size("10B") == 10
    assert memory_size(" 10  B ") == 10
    assert memory_size("10.4B") == 10

    assert memory_size("10") == 10
    assert memory_size(" 10 ") == 10
    assert memory_size("10.4") == 10

    # Must be a Bytes unit.
    with pytest.raises(ParseError):
        memory_size("1ft")
    with pytest.raises(ParseError):
        memory_size("1m")

    # Invalid input.
    with pytest.raises(ParseError):
        memory_size("")
    with pytest.raises(ParseError):
        memory_size("foo")


def test_flatten_shlexed_list() -> None:
    assert _flatten_shlexed_list(["arg1", "arg2"]) == ["arg1", "arg2"]
    assert _flatten_shlexed_list(["arg1 arg2"]) == ["arg1", "arg2"]
    assert _flatten_shlexed_list(["arg1 arg2=foo", "--arg3"]) == ["arg1", "arg2=foo", "--arg3"]
    assert _flatten_shlexed_list(["arg1='foo bar'", "arg2='baz'"]) == [
        "arg1=foo bar",
        "arg2=baz",
    ]


@pytest.mark.parametrize(
    "unit,key",
    [
        ("s", "seconds"),
        ("second", "seconds"),
        ("seconds", "seconds"),
        ("ms", "milliseconds"),
        ("milli", "milliseconds"),
        ("millis", "milliseconds"),
        ("millisecond", "milliseconds"),
        ("milliseconds", "milliseconds"),
        ("us", "microseconds"),
        ("micro", "microseconds"),
        ("micros", "microseconds"),
        ("microsecond", "microseconds"),
        ("microseconds", "microseconds"),
        ("m", "minutes"),
        ("minute", "minutes"),
        ("minutes", "minutes"),
        ("h", "hours"),
        ("hour", "hours"),
        ("hours", "hours"),
    ],
)
def test_duration_accepts_units(unit, key) -> None:
    assert duration(f"10{unit}") == timedelta(**{key: 10})


class TestCustomTypes:
    @staticmethod
    def assert_list_parsed(s: str, *, expected: ParsedList) -> None:
        assert expected == ListValueComponent.create(s).val

    @staticmethod
    def assert_split_list(s: str, *, expected: List[str]) -> None:
        assert expected == ListValueComponent._split_modifier_expr(s)

    def test_unset_bool(self):
        # UnsetBool should only be use-able as a singleton value via its type.
        with pytest.raises(NotImplementedError):
            UnsetBool()

    def test_dict(self) -> None:
        def assert_dict_parsed(s: str, *, expected: ParsedDict) -> None:
            assert expected == DictValueComponent.create(s).val

        assert_dict_parsed("{}", expected={})
        assert_dict_parsed('{ "a": "b" }', expected={"a": "b"})
        assert_dict_parsed("{ 'a': 'b' }", expected={"a": "b"})
        assert_dict_parsed('{ "a": [1, 2, 3] }', expected={"a": [1, 2, 3]})
        assert_dict_parsed('{ "a": [1, 2] + [3, 4] }', expected={"a": [1, 2, 3, 4]})

        def assert_dict_error(s: str) -> None:
            with pytest.raises(ParseError):
                assert_dict_parsed(s, expected={})

        assert_dict_error("[]")
        assert_dict_error("[1, 2, 3]")
        assert_dict_error("1")
        assert_dict_error('"a"')

    def test_list(self) -> None:
        self.assert_list_parsed("[]", expected=[])
        self.assert_list_parsed("[1, 2, 3]", expected=[1, 2, 3])
        self.assert_list_parsed("(1, 2, 3)", expected=[1, 2, 3])
        self.assert_list_parsed('["a", "b", "c"]', expected=["a", "b", "c"])
        self.assert_list_parsed("['a', 'b', 'c']", expected=["a", "b", "c"])
        self.assert_list_parsed("[1, 2] + [3, 4]", expected=[1, 2, 3, 4])
        self.assert_list_parsed("(1, 2) + (3, 4)", expected=[1, 2, 3, 4])
        self.assert_list_parsed('a"', expected=['a"'])
        self.assert_list_parsed("a'", expected=["a'"])
        self.assert_list_parsed("\"a'", expected=["\"a'"])
        self.assert_list_parsed("'a\"", expected=["'a\""])
        self.assert_list_parsed('a"""a', expected=['a"""a'])
        self.assert_list_parsed("1,2", expected=["1,2"])
        self.assert_list_parsed("+[1,2]", expected=[1, 2])
        self.assert_list_parsed("\\", expected=["\\"])

    def test_split_list_modifier_expressions(self) -> None:
        self.assert_split_list("1", expected=["1"])
        self.assert_split_list("foo", expected=["foo"])
        self.assert_split_list("1,2", expected=["1,2"])
        self.assert_split_list("[1,2]", expected=["[1,2]"])
        self.assert_split_list("[1,2],[3,4]", expected=["[1,2],[3,4]"])
        self.assert_split_list("+[1,2],[3,4]", expected=["+[1,2],[3,4]"])
        self.assert_split_list("[1,2],-[3,4]", expected=["[1,2],-[3,4]"])
        self.assert_split_list("+[1,2],foo", expected=["+[1,2],foo"])

        self.assert_split_list("+[1,2],-[3,4]", expected=["+[1,2]", "-[3,4]"])
        self.assert_split_list("-[1,2],+[3,4]", expected=["-[1,2]", "+[3,4]"])
        self.assert_split_list(
            "-[1,2],+[3,4],-[5,6],+[7,8]", expected=["-[1,2]", "+[3,4]", "-[5,6]", "+[7,8]"]
        )
        self.assert_split_list("+[-1,-2],-[-3,-4]", expected=["+[-1,-2]", "-[-3,-4]"])
        self.assert_split_list('+["-"],-["+"]', expected=['+["-"]', '-["+"]'])
        self.assert_split_list('+["+[3,4]"],-["-[4,5]"]', expected=['+["+[3,4]"]', '-["-[4,5]"]'])

        # Spot-check that this works with literal tuples as well as lists.
        self.assert_split_list("+(1,2),-(3,4)", expected=["+(1,2)", "-(3,4)"])
        self.assert_split_list(
            "-[1,2],+[3,4],-(5,6),+[7,8]", expected=["-[1,2]", "+[3,4]", "-(5,6)", "+[7,8]"]
        )
        self.assert_split_list("+(-1,-2),-[-3,-4]", expected=["+(-1,-2)", "-[-3,-4]"])
        self.assert_split_list('+("+(3,4)"),-("-(4,5)")', expected=['+("+(3,4)")', '-("-(4,5)")'])

        # Check that whitespace around the comma is OK.
        self.assert_split_list("+[1,2] , -[3,4]", expected=["+[1,2]", "-[3,4]"])
        self.assert_split_list("+[1,2]    ,-[3,4]", expected=["+[1,2]", "-[3,4]"])
        self.assert_split_list("+[1,2] ,     -[3,4]", expected=["+[1,2]", "-[3,4]"])

        # We will split some invalid expressions, but that's OK, we'll error out later on the
        # broken components.
        self.assert_split_list("+1,2],-[3,4", expected=["+1,2]", "-[3,4"])
        self.assert_split_list("+(1,2],-[3,4)", expected=["+(1,2]", "-[3,4)"])

    @pytest.mark.xfail(
        reason="The heuristic list modifier expression splitter cannot handle certain very unlikely cases."
    )
    def test_split_unlikely_list_modifier_expression(self) -> None:
        # Example of the kind of (unlikely) values that will defeat our heuristic, regex-based
        # splitter of list modifier expressions.
        funky_string = "],+["
        self.assert_split_list(
            f'+["{funky_string}"],-["foo"]', expected=[f'+["{funky_string}"]', '-["foo"]']
        )

    def test_unicode_comments(self) -> None:
        """We had a bug where unicode characters in comments would cause the option parser to fail.

        Without the fix to the option parser, this test case reproduces the error:

        UnicodeDecodeError: 'ascii' codec can't decode byte 0xe2 in position 44:
                           ordinal not in range(128)
        """
        self.assert_list_parsed(
            dedent(
                """
                [
                    'Hi there!',
                    # This is a comment with ‘sneaky‘ unicode characters.
                    'This is an element in a list of strings.',
                    # This is a comment with an obvious unicode character ☺.
                ]
                """
            ).strip(),
            expected=["Hi there!", "This is an element in a list of strings."],
        )
