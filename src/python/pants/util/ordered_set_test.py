# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import random
from typing import AbstractSet, Iterator, Sequence, Tuple, Type, Union

import pytest

from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

OrderedSetInstance = Union[OrderedSet, FrozenOrderedSet]
OrderedSetCls = Union[Type[OrderedSet], Type[FrozenOrderedSet]]


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_stable_order(cls: OrderedSetCls) -> None:
    set1 = cls("abracadabra")
    assert len(set1) == 5
    assert list(set1) == ["a", "b", "r", "c", "d"]
    assert list(reversed(set1)) == ["d", "c", "r", "b", "a"]


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_contains(cls: OrderedSetCls) -> None:
    set1 = cls("abracadabra")
    assert "a" in set1
    assert "r" in set1
    assert "z" not in set1
    assert 0 not in set1


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_copy(cls: OrderedSetCls) -> None:
    set1 = cls("abc")
    set2 = set1.copy()
    assert set1 == set2
    assert set1 is set1
    assert set2 is set2
    assert set1 is not set2


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_get_by_index(cls: OrderedSetCls) -> None:
    set1 = cls("abracadabra")
    assert set1[0] == "a"
    assert set1[1] == "b"
    assert set1[2] == "r"
    assert set1[3] == "c"
    assert set1[4] == "d"
    with pytest.raises(IndexError):
        set1[5]


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_slices(cls: OrderedSetCls) -> None:
    set1 = cls("abracadabra")
    assert set1[:] == set1
    assert set1[:] is not set1
    assert set1[1:3] == cls(["b", "r"])


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_find_index(cls: OrderedSetCls) -> None:
    set1 = cls("abc")
    assert set1.index("a") == 0
    assert set1.index("b") == 1
    assert set1.index("c") == 2

    with pytest.raises(ValueError):
        set1.index("z")
    with pytest.raises(ValueError):
        set1.index("a", start=1)
    with pytest.raises(ValueError):
        set1.index("c", end=2)
    with pytest.raises(ValueError):
        set1.index("b", start=1, end=1)


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_tuples(cls: OrderedSetCls) -> None:
    tup = ("tuple", 1)
    set1 = OrderedSet([tup])
    assert set1.index(tup) == 0
    assert set1[0] == tup


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_repr(cls: OrderedSetCls) -> None:
    set1 = cls()
    assert repr(set1) == f"{cls.__name__}()"

    set2 = cls("abcabc")
    assert repr(set2) == f"{cls.__name__}(['a', 'b', 'c'])"


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_equality(cls: OrderedSetCls) -> None:
    set1 = cls([1, 2])

    assert set1 == cls([1, 2])
    assert set1 == cls([1, 1, 2, 2])

    assert set1 != cls([2, 1])
    assert set1 != [2, 1]
    assert set1 != [2, 1, 1]

    assert set1 != [1, 2]
    assert set1 != (1, 2)
    assert set1 != {1, 2}
    assert set1 != {1: None, 2: None}

    # We are strict in enforcing that FrozenOrderedSet != OrderedSet. This is important for the
    # engine, where we should never use OrderedSet.
    other_cls = FrozenOrderedSet if cls == OrderedSet else OrderedSet
    assert set1 != other_cls([1, 2])


def test_frozen_is_hashable() -> None:
    set1 = FrozenOrderedSet("abcabc")
    assert hash(set1) == hash(set1.copy())
    assert hash(set1) == hash(("a", "b", "c"))

    set2 = FrozenOrderedSet("abcd")
    assert hash(set1) != hash(set2)
    assert hash(set1) != hash(("a", "b", "c", "d"))


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_binary_operations(cls: OrderedSetCls) -> None:
    set1 = cls("abracadabra")
    set2 = cls("simsalabim")
    assert set1 != set2

    assert set1 & set2 == cls(["a", "b"])
    assert set1 | set2 == cls(["a", "b", "r", "c", "d", "s", "i", "m", "l"])
    assert set1 - set2 == cls(["r", "c", "d"])


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_comparisons(cls: OrderedSetCls) -> None:
    # Comparison operators on sets actually test for subset and superset.
    assert cls([1, 2]) < cls([1, 2, 3])
    assert cls([1, 2]) > cls([1])


def test_add() -> None:
    set1: OrderedSet[str] = OrderedSet()

    set1.add("a")
    assert set1 == OrderedSet("a")

    set1.add("b")
    assert set1 == OrderedSet("ab")

    set1.add("a")
    assert set1 == OrderedSet("ab")


def test_update() -> None:
    set1 = OrderedSet("abcd")
    set1.update("efgh")

    assert len(set1) == 8
    assert "".join(set1) == "abcdefgh"

    set2 = OrderedSet("abcd")
    set2.update("cdef")
    assert len(set2) == 6
    assert "".join(set2) == "abcdef"


def test_remove() -> None:
    set1 = OrderedSet("abracadabra")

    set1.remove("a")
    set1.remove("b")

    assert set1 == OrderedSet("rcd")
    assert set1[0] == "r"
    assert set1[1] == "c"
    assert set1[2] == "d"

    assert set1.index("r") == 0
    assert set1.index("c") == 1
    assert set1.index("d") == 2

    assert "a" not in set1
    assert "b" not in set1
    assert "r" in set1

    # Make sure we can .discard() something that's already gone, plus something that was never
    # there.
    set1.discard("a")
    set1.discard("a")

    # If we .remove() an element that's not there, we get a KeyError.
    with pytest.raises(KeyError):
        set1.remove("z")


def test_pop() -> None:
    set1 = OrderedSet("ab")
    elem = set1.pop()

    assert elem == "b"
    assert set1 == OrderedSet("a")
    elem = set1.pop()

    assert elem == "a"
    assert set1 == OrderedSet()

    with pytest.raises(KeyError):
        set1.pop()


def test_clear() -> None:
    set1 = OrderedSet("abracadabra")
    set1.clear()

    assert len(set1) == 0
    assert set1 == OrderedSet()


def assert_results_are_the_same(
    results: Union[Sequence[AbstractSet], Sequence[bool]],
    *,
    sets: Tuple[OrderedSetInstance, OrderedSetInstance],
) -> None:
    """Check that all results have the same value, but are different items."""
    assert all(
        result == results[0] for result in results
    ), f"Not all results are the same.\nResults: {results}\nTest data: {sets}"
    for a, b in itertools.combinations(results, r=2):
        if isinstance(a, bool):
            continue
        assert a is not b, (
            "The results should all be distinct OrderedSet or FrozenOrderedSet instances. "
            f"{a} is the same object as {b}."
        )


def generate_testdata(
    cls: OrderedSetCls,
) -> Iterator[Tuple[OrderedSetInstance, OrderedSetInstance]]:
    data1 = cls([5, 3, 1, 4])
    data2 = cls([1, 4])
    yield data1, data2

    # First set is empty
    data1 = cls([])
    data2 = cls([3, 1, 2])
    yield data1, data2

    # Second set is empty
    data1 = cls([3, 1, 2])
    data2 = cls([])
    yield data1, data2

    # Both sets are empty
    data1 = cls([])
    data2 = cls([])
    yield data1, data2

    # Random test cases
    rng = random.Random(0)
    a, b = 20, 20
    for _ in range(10):
        data1 = cls(rng.randint(0, a) for _ in range(b))
        data2 = cls(rng.randint(0, a) for _ in range(b))
        yield data1, data2
        yield data2, data1


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_intersection(cls: OrderedSetCls) -> None:
    for set1, set2 in generate_testdata(cls):
        results = [set1 & set2, set1.intersection(set2)]
        if isinstance(set1, OrderedSet):
            mutation_result1 = set1.copy()
            mutation_result1.intersection_update(set2)
            results.append(mutation_result1)

            mutation_result2 = set1.copy()
            mutation_result2 &= set2  # type: ignore[misc]
            results.append(mutation_result2)
        assert_results_are_the_same(results, sets=(set1, set2))


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_difference(cls: OrderedSetCls) -> None:
    for set1, set2 in generate_testdata(cls):
        results = [set1 - set2, set1.difference(set2)]
        if isinstance(set1, OrderedSet):
            mutation_result1 = set1.copy()
            mutation_result1.difference_update(set2)
            results.append(mutation_result1)

            mutation_result2 = set1.copy()
            mutation_result2 -= set2  # type: ignore[misc]
            results.append(mutation_result2)
        assert_results_are_the_same(results, sets=(set1, set2))


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_xor(cls: OrderedSetCls) -> None:
    for set1, set2 in generate_testdata(cls):
        results = [set1 ^ set2, set1.symmetric_difference(set2)]
        if isinstance(set1, OrderedSet):
            mutation_result1 = set1.copy()
            mutation_result1.symmetric_difference_update(set2)
            results.append(mutation_result1)

            mutation_result2 = set1.copy()
            mutation_result2 ^= set2  # type: ignore[misc]
            results.append(mutation_result2)
        assert_results_are_the_same(results, sets=(set1, set2))


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_union(cls: OrderedSetCls) -> None:
    for set1, set2 in generate_testdata(cls):
        results = [set1 | set2, set1.union(set2)]
        if isinstance(set1, OrderedSet):
            mutation_result1 = set1.copy()
            mutation_result1.update(set2)
            results.append(mutation_result1)

            mutation_result2 = set1.copy()
            mutation_result2 |= set2  # type: ignore[misc]
            results.append(mutation_result2)
        assert_results_are_the_same(results, sets=(set1, set2))


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_subset(cls: OrderedSetCls) -> None:
    for set1, set2 in generate_testdata(cls):
        result1 = set1 <= set2
        result2 = set1.issubset(set2)
        result3 = set(set1).issubset(set(set2))
        assert_results_are_the_same([result1, result2, result3], sets=(set1, set2))


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_superset(cls: OrderedSetCls) -> None:
    for set1, set2 in generate_testdata(cls):
        result1 = set1 >= set2
        result2 = set1.issuperset(set2)
        result3 = set(set1).issuperset(set(set2))
        assert_results_are_the_same([result1, result2, result3], sets=(set1, set2))


@pytest.mark.parametrize("cls", [OrderedSet, FrozenOrderedSet])
def test_disjoint(cls: OrderedSetCls) -> None:
    for set1, set2 in generate_testdata(cls):
        result1 = set1.isdisjoint(set2)
        result2 = len(set1.intersection(set2)) == 0
        assert_results_are_the_same([result1, result2], sets=(set1, set2))
