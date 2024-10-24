# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
from dataclasses import dataclass

from pants.engine.unions import (
    UnionMembership,
    UnionRule,
    distinct_union_type_per_subclass,
    is_union,
    union,
)
from pants.util.ordered_set import FrozenOrderedSet


def test_simple() -> None:
    @union
    class Fruit:
        pass

    class Banana(Fruit):
        pass

    class Apple(Fruit):
        pass

    @union
    class CitrusFruit(Fruit):
        pass

    class Orange(CitrusFruit):
        pass

    @union
    class Vegetable:
        pass

    class Potato:  # Doesn't _have_ to inherit from the union
        pass

    union_membership = UnionMembership.from_rules(
        [
            UnionRule(Fruit, Banana),
            UnionRule(Fruit, Apple),
            UnionRule(CitrusFruit, Orange),
            UnionRule(Vegetable, Potato),
        ]
    )

    assert union_membership == UnionMembership(
        {
            Fruit: FrozenOrderedSet([Banana, Apple]),
            CitrusFruit: FrozenOrderedSet([Orange]),
            Vegetable: FrozenOrderedSet([Potato]),
        }
    )


def test_distinct_union_per_subclass() -> None:
    class Pasta:
        @distinct_union_type_per_subclass
        @dataclass
        class Shape:
            round: bool

    class Spaghetti(Pasta):
        pass

    class Rigatoni(Pasta):
        pass

    assert Pasta.Shape is Pasta.Shape
    assert Spaghetti.Shape is Spaghetti.Shape
    assert Rigatoni.Shape is Rigatoni.Shape
    assert Pasta.Shape is not Spaghetti.Shape
    assert Pasta.Shape is not Rigatoni.Shape
    assert Spaghetti.Shape is not Rigatoni.Shape
    assert dataclasses.is_dataclass(Pasta.Shape)
    assert dataclasses.is_dataclass(Spaghetti.Shape)
    assert dataclasses.is_dataclass(Rigatoni.Shape)
    assert Pasta.Shape(True).round
    assert Spaghetti.Shape(True).round
    assert Rigatoni.Shape(True).round

    # Also on class instances, just spot-checking
    assert Pasta().Shape is Pasta.Shape
    assert Pasta().Shape is Pasta().Shape
    assert Pasta().Shape is not Spaghetti().Shape
    assert Pasta().Shape is not Spaghetti.Shape

    assert is_union(Pasta.Shape)
    assert is_union(Spaghetti.Shape)
    assert is_union(Rigatoni.Shape)
