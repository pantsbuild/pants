# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

import pytest

from pants.engine.addresses import Address
from pants.engine.internals.parametrize import Parametrize


@pytest.mark.parametrize(
    "expected,args,kwargs",
    [
        ({"a": "a"}, ["a"], {}),
        ({"a": "a", "b": "c"}, ["a"], {"b": "c"}),
        ({"b": "c"}, [], {"b": "c"}),
        ({"b": 1}, [], {"b": 1}),
    ],
)
def test_to_parameters_success(
    expected: dict[str, Any], args: list[str], kwargs: dict[str, Any]
) -> None:
    assert expected == Parametrize(*args, **kwargs).to_parameters()


@pytest.mark.parametrize(
    "exception_str,args,kwargs",
    [
        ("Positional arguments must be strings", [1], {}),
        (
            "Positional arguments cannot have the same name as keyword arguments",
            ["x"],
            {"x": 1},
        ),
        ("Positional argument `@` contained separator characters", ["@"], {}),
    ],
)
def test_to_parameters_failure(exception_str: str, args: list[Any], kwargs: dict[str, Any]) -> None:
    with pytest.raises(Exception) as exc:
        Parametrize(*args, **kwargs).to_parameters()
    assert exception_str in str(exc.value)


@pytest.mark.parametrize(
    "expected,fields",
    [
        ([("a:a", {"f": "b"})], {"f": "b"}),
        ([("a:a@f=b", {"f": "b"})], {"f": Parametrize("b")}),
        (
            [
                ("a:a@f=b", {"f": "b"}),
                ("a:a@f=c", {"f": "c"}),
            ],
            {"f": Parametrize("b", "c")},
        ),
        (
            [
                ("a:a@f=b,x=d", {"f": "b", "x": "d"}),
                ("a:a@f=b,x=e", {"f": "b", "x": "e"}),
                ("a:a@f=c,x=d", {"f": "c", "x": "d"}),
                ("a:a@f=c,x=e", {"f": "c", "x": "e"}),
            ],
            {"f": Parametrize("b", "c"), "x": Parametrize("d", "e")},
        ),
    ],
)
def test_expand(
    expected: list[tuple[str, dict[str, Any]]], fields: dict[str, Any | Parametrize]
) -> None:
    assert sorted(expected) == sorted(
        (address.spec, result_fields)
        for address, result_fields in Parametrize.expand(Address("a"), fields)
    )
