# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import OrderedDict
from dataclasses import dataclass

import pytest

from pants.util.frozendict import FrozenDict


def test_flexible_constructor() -> None:
    expected = FrozenDict({"a": 0, "b": 1})
    assert FrozenDict(OrderedDict({"a": 0, "b": 1})) == expected
    assert FrozenDict([("a", 0), ("b", 1)]) == expected
    assert FrozenDict((("a", 0), ("b", 1))) == expected
    assert FrozenDict(a=0, b=1) == expected
    assert FrozenDict({"a": 0}, b=1) == expected
    assert FrozenDict([("a", 0)], b=1) == expected


def test_empty_construction() -> None:
    assert FrozenDict() == FrozenDict({})


def test_invalid_arguments() -> None:
    with pytest.raises(ValueError):
        FrozenDict({}, {})  # type: ignore[call-overload]


def test_unhashable_items_rejected() -> None:
    with pytest.raises(TypeError):
        FrozenDict({[]: 0})
    with pytest.raises(TypeError):
        FrozenDict({0: []})


def test_original_data_gets_copied() -> None:
    d1 = {"a": 0, "b": 1}
    fd1 = FrozenDict(d1)
    d1.clear()
    assert fd1 == FrozenDict({"a": 0, "b": 1})


def test_len() -> None:
    assert len(FrozenDict()) == 0
    assert len(FrozenDict({"a": 0, "b": 1})) == 2


def test_contains() -> None:
    fd1 = FrozenDict({"a": 0})
    assert "a" in fd1
    assert "z" not in fd1
    assert object() not in fd1


def test_get() -> None:
    fd1 = FrozenDict({"a": 0})
    assert fd1["a"] == 0
    assert fd1.get("a") == 0

    with pytest.raises(KeyError):
        fd1["z"]
    assert fd1.get("z") is None
    assert fd1.get("z", 26) == 26


def test_iter() -> None:
    fd1 = FrozenDict({"a": 0, "b": 1})
    assert list(iter(fd1)) == ["a", "b"]
    assert [k for k in fd1] == ["a", "b"]


def test_keys() -> None:
    d1 = {"a": 0, "b": 1}
    assert FrozenDict(d1).keys() == d1.keys()


def test_values() -> None:
    d1 = {"a": 0, "b": 1}
    # __eq__ seems to be busted for dict.values()...d1.values() != d1.values().
    assert list(FrozenDict(d1).values()) == list(d1.values())


def test_items() -> None:
    d1 = {"a": 0, "b": 1}
    assert FrozenDict(d1).items() == d1.items()


def test_eq() -> None:
    d1 = {"a": 0, "b": 1}
    fd1 = FrozenDict(d1)
    assert fd1 == fd1
    assert fd1 == FrozenDict(d1)
    # Order matters.
    assert fd1 != FrozenDict({"b": 1, "a": 0})
    # Must be an instance of FrozenDict.
    assert fd1 != d1


def test_hash() -> None:
    d1 = {"a": 0, "b": 1}
    assert hash(FrozenDict(d1)) == hash(FrozenDict(d1))
    # Order matters.
    assert hash(FrozenDict(d1)) != hash(FrozenDict({"b": 1, "a": 0}))


def test_works_with_dataclasses() -> None:
    @dataclass(frozen=True)
    class Frozen:
        x: int

    @dataclass
    class Mutable:
        x: int

    fd1 = FrozenDict({"a": Frozen(0)})
    fd2 = FrozenDict({Frozen(0): "a"})
    assert hash(fd1) == hash(fd1)
    assert hash(fd2) == hash(fd2)
    assert hash(fd1) != hash(fd2)

    with pytest.raises(TypeError):
        FrozenDict({Mutable(0): "a"})
    with pytest.raises(TypeError):
        FrozenDict({"a": Mutable(0)})
