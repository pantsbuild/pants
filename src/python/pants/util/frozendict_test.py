# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict

import pytest

from pants.util.frozendict import FrozenDict, LazyFrozenDict


def test_flexible_constructor() -> None:
    expected = FrozenDict({"a": 0, "b": 1})
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
    assert list(fd1) == ["a", "b"]


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
    # Order doesn't matter.
    assert fd1 == FrozenDict({"b": 1, "a": 0})
    # A FrozenDict is equal to plain `dict`s with equivalent contents.
    assert fd1 == d1
    assert d1 == fd1

    # A different dict is not equal.
    d2 = {"a": 1, "b": 0}
    fd2 = FrozenDict(d2)
    assert fd2 != fd1
    assert fd1 != d2
    assert d2 != fd1


def test_lt() -> None:
    d = {"a": 0, "b": 1}

    ordered = [
        {"a": 0},
        d,
        {"a": 0, "b": 2},
        {"a": 1},
        {"a": 1, "b": 0},
        {"b": -1},
        {"c": -2},
    ]
    # Do all comparisions: the list is in order, so the comparisons of the dicts should match the
    # comparison of indices.
    for i, di in enumerate(ordered):
        for j, dj in enumerate(ordered):
            assert (FrozenDict(di) < FrozenDict(dj)) == (i < j)

    # Order doesn't matter.
    assert FrozenDict(d) < FrozenDict({"b": 2, "a": 0})

    # Must be an instance of FrozenDict.
    with pytest.raises(TypeError):
        FrozenDict(d) < d


def test_hash() -> None:
    d1 = {"a": 0, "b": 1}
    assert hash(FrozenDict(d1)) == hash(FrozenDict(d1))
    # Order doesn't matters.
    assert hash(FrozenDict(d1)) == hash(FrozenDict({"b": 1, "a": 0}))

    # Confirm that `hash` is likely doing something "correct", and not just implemented as `return
    # 0` or similar.
    unique_hashes = set()
    for i in range(1000):
        unique_hashes.add(hash(FrozenDict({"a": i, "b": i})))

    # It would be incredibly unlikely for 1000 different examples to have so many collisions that we
    # saw fewer than 500 unique hash values. (It would be unlikely to see even one collision
    # assuming `hash` acts like a uniform random variable: by
    # https://en.wikipedia.org/wiki/Birthday_problem, the probability of seeing a single collision
    # with m = 2**64 (the size of the output of hash) and n = 1000 is approximately n**2/(2*m) =
    # 2.7e-14).
    assert len(unique_hashes) >= 500


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


def test_lazy_frozen_dict() -> None:
    loaded: DefaultDict[str, int] = defaultdict(int)

    def load_value(s: str) -> str:
        loaded[s] += 1
        return "".join(reversed(s))

    ld1 = LazyFrozenDict({"a": lambda: load_value("1234"), "b": lambda: load_value("abcd")})
    hashvalue = hash(ld1)
    assert len(ld1) == 2
    assert len(loaded) == 0

    # Test memoization, that we don't invoke the loader twice.
    assert ld1["b"] == "dcba"
    assert ld1["b"] == "dcba"

    assert loaded == {"abcd": 1}
    assert ld1["a"] == "4321"
    assert len(loaded) == 2

    # Hash value should be stable regardless if we've loaded the values or not.
    assert hash(ld1) == hashvalue


def test_frozendict_dot_frozen() -> None:
    a = {1: 2}
    b = FrozenDict(a)
    frozen_a = FrozenDict.frozen(a)
    frozen_b = FrozenDict.frozen(b)

    assert frozen_a == FrozenDict(a)
    assert frozen_b is b
