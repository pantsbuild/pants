# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Callable

from pants.util.filtering import and_filters, create_filter, create_filters


def is_divisible_by(divisor_str: str) -> Callable[[int], bool]:
    return lambda n: n % int(divisor_str) == 0


def test_create_filter() -> None:
    divisible_by_2 = create_filter("2", is_divisible_by)
    assert divisible_by_2(2) is True
    assert divisible_by_2(3) is False
    assert divisible_by_2(4) is True
    assert divisible_by_2(6) is True


def test_create_filters() -> None:
    # This tests that create_filters() properly captures different closures.
    divisible_by_2, divisible_by_3 = create_filters(["2", "3"], is_divisible_by)
    assert divisible_by_2(2) is True
    assert divisible_by_2(3) is False
    assert divisible_by_2(4) is True
    assert divisible_by_2(6) is True

    assert divisible_by_3(2) is False
    assert divisible_by_3(3) is True
    assert divisible_by_3(4) is False
    assert divisible_by_3(6) is True


def test_and_filters() -> None:
    divisible_by_6 = and_filters(create_filters(["2", "3"], is_divisible_by))
    assert divisible_by_6(2) is False
    assert divisible_by_6(3) is False
    assert divisible_by_6(6) is True
    assert divisible_by_6(9) is False
    assert divisible_by_6(12) is True


def test_list_filter() -> None:
    divisible_by_2_or_3 = create_filter("2,3", is_divisible_by)
    assert divisible_by_2_or_3(2) is True
    assert divisible_by_2_or_3(3) is True
    assert divisible_by_2_or_3(4) is True
    assert divisible_by_2_or_3(5) is False
    assert divisible_by_2_or_3(6) is True


def test_explicit_plus_filter() -> None:
    divisible_by_2_or_3 = create_filter("+2,3", is_divisible_by)
    assert divisible_by_2_or_3(2) is True
    assert divisible_by_2_or_3(3) is True
    assert divisible_by_2_or_3(4) is True
    assert divisible_by_2_or_3(5) is False
    assert divisible_by_2_or_3(6) is True


def test_negated_filter() -> None:
    # This tests that the negation applies to the entire list.
    coprime_to_2_and_3 = create_filter("-2,3", is_divisible_by)
    assert coprime_to_2_and_3(2) is False
    assert coprime_to_2_and_3(3) is False
    assert coprime_to_2_and_3(4) is False
    assert coprime_to_2_and_3(5) is True
    assert coprime_to_2_and_3(6) is False


def test_merged_filter() -> None:
    # This tests that multiple filters are merged into a single consistent filter
    divisible_by_3_and_not_2 = and_filters(
        create_filters(
            ["-3", "-2", "+3"],
            is_divisible_by,
        )
    )
    assert divisible_by_3_and_not_2(2) is False
    assert divisible_by_3_and_not_2(3) is True
    assert divisible_by_3_and_not_2(4) is False
    assert divisible_by_3_and_not_2(5) is False
    assert divisible_by_3_and_not_2(6) is False
    assert divisible_by_3_and_not_2(7) is False
    assert divisible_by_3_and_not_2(8) is False
    assert divisible_by_3_and_not_2(9) is True


def test_merged_filter_coprime() -> None:
    # This tests that multiple filters are merged into a single consistent filter
    coprime_to_2_and_3_and_divisible_by_7 = and_filters(
        create_filters(
            ["-2,3", "+7"],
            is_divisible_by,
        )
    )

    assert coprime_to_2_and_3_and_divisible_by_7(1) is False
    assert coprime_to_2_and_3_and_divisible_by_7(2) is False
    assert coprime_to_2_and_3_and_divisible_by_7(3) is False
    assert coprime_to_2_and_3_and_divisible_by_7(4) is False
    assert coprime_to_2_and_3_and_divisible_by_7(5) is False
    assert coprime_to_2_and_3_and_divisible_by_7(7) is True
    assert coprime_to_2_and_3_and_divisible_by_7(34) is False
    assert coprime_to_2_and_3_and_divisible_by_7(35) is True
