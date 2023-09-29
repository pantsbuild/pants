# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.collection import Collection, DeduplicatedCollection


class Examples(Collection[int]):
    """A new type to ensure that subclassing works properly."""


class Examples2(Collection[int]):
    pass


def test_collection_contains() -> None:
    c1 = Collection([1, 2])
    assert 1 in c1
    assert 2 in c1
    assert 200 not in c1
    assert "bad" not in c1  # type: ignore[comparison-overlap]


def test_collection_iteration() -> None:
    c1 = Collection([1, 2])
    assert list(iter(c1)) == [1, 2]
    assert list(c1) == [1, 2]


def test_collection_length() -> None:
    assert len(Collection([])) == 0
    assert len(Collection([1, 2])) == 2


def test_collection_index() -> None:
    c1 = Collection([0, 1, 2])
    assert c1[0] == 0
    assert c1[-1] == 2

    assert c1[:] == c1
    assert c1[1:] == Collection([1, 2])
    assert c1[:1] == Collection([0])
    assert c1[:-1] == Collection([0, 1])


def test_collection_reversed() -> None:
    assert list(reversed(Collection([1, 2, 3]))) == [3, 2, 1]


def test_collection_equality() -> None:
    assert () != Collection()  # type: ignore[comparison-overlap]
    assert Collection() != ()  # type: ignore[comparison-overlap]

    assert Collection([]) == Collection([])
    c1 = Collection([1, 2, 3])
    assert c1 == Collection([1, 2, 3])

    assert c1 != Collection([3, 2, 1])
    assert c1 != Collection([])
    assert c1 != Collection([1, 2])

    e1 = Examples([1, 2, 3])
    assert e1 == Examples([1, 2, 3])
    assert e1 != Examples2([1, 2, 3])  # type: ignore[comparison-overlap]


def test_collection_hash() -> None:
    assert hash(Collection([])) == hash(Collection([]))

    c1 = Collection([1, 2, 3])
    assert hash(c1) == hash(Collection([1, 2, 3]))
    assert hash(c1) == hash(Examples([1, 2, 3]))


def test_collection_bool() -> None:
    assert bool(Collection([0])) is True
    assert bool(Collection([])) is False


def test_collection_repr() -> None:
    assert repr(Collection([])) == "Collection(())"
    assert repr(Examples([])) == "Examples(())"
    assert repr(Collection([1, 2, 3])) == "Collection((1, 2, 3))"
    assert repr(Examples([1, 2, 3])) == "Examples((1, 2, 3))"


def test_deduplicated_collection() -> None:
    # NB: most of the functionality, like testing .union() and .intersection(), is tested
    # exhaustively in the tests for FrozenOrderedSet. Here, we only have a couple basic
    # smoke-screen tests to ensure things work properly.
    class DedupedExamples(DeduplicatedCollection[int]):
        sort_input = True

    class DedupedExamples2(DeduplicatedCollection[int]):
        sort_input = False

    # Test deduplication
    assert len(DeduplicatedCollection([1, 1, 1, 2])) == 2

    # Test equality, especially that object identity matters
    assert DedupedExamples([0]) == DedupedExamples([0])
    assert DedupedExamples([0]) != DedupedExamples2([0])

    # Test hash
    c = DeduplicatedCollection([0, 1, 2])
    assert hash(c) == hash(DeduplicatedCollection([0, 1, 2]))
    assert hash(c) != hash(DeduplicatedCollection([0, 1]))

    # Test contains
    assert 2 in DeduplicatedCollection([0, 1, 2])
    assert 20 not in DeduplicatedCollection([0, 1, 2])

    # Test sorting
    assert list(DedupedExamples([2, 1])) == [1, 2]
    assert list(DedupedExamples2([2, 1])) == [2, 1]

    # Test the interaction of sorting with equality
    assert DedupedExamples([2, 1]) == DedupedExamples([1, 2])
    assert DedupedExamples2([2, 1]) != DedupedExamples2([1, 2])

    # Test bool
    assert bool(DeduplicatedCollection([])) is False
    assert bool(DeduplicatedCollection([1])) is True

    # Test repr
    assert repr(DedupedExamples()) == "DedupedExamples([])"
    assert repr(DedupedExamples([0, 1])) == "DedupedExamples([0, 1])"
