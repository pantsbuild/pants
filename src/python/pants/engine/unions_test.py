# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.unions import UnionMembership, UnionRule, union
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

    assert UnionMembership.from_rules(
        [
            UnionRule(Fruit, Banana),
            UnionRule(Fruit, Apple),
            UnionRule(CitrusFruit, Orange),
            UnionRule(Vegetable, Potato),
        ]
    ) == UnionMembership(
        {
            Fruit: FrozenOrderedSet([Banana, Apple]),
            CitrusFruit: FrozenOrderedSet([Orange, Banana, Apple]),
            Vegetable: FrozenOrderedSet([Potato]),
        }
    )
