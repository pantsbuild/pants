# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.ordered_set import FrozenOrderedSet


def test_simple() -> None:
    @union
    class Fruit:
        pass

    class Strawberry(Fruit):
        pass

    class Apple(Fruit):
        pass

    @union
    class TropicalFruit(Fruit):
        pass

    class Mango(TropicalFruit):
        pass

    @union
    class CitrusFruit(TropicalFruit):
        pass

    class Orange(CitrusFruit):
        pass

    @union
    class Vegetable:
        pass

    class Zucchini:  # Doesn't _have_ to inherit from the union
        pass

    class Tubers(Vegetable):
        pass

    # Also test a non-union middle-ancestor
    @union
    class StarchyTubers(Tubers):
        pass

    class Potato(StarchyTubers):
        pass

    union_membership = UnionMembership.from_rules(
        [
            UnionRule(Fruit, Strawberry),
            UnionRule(Fruit, Apple),
            UnionRule(TropicalFruit, Mango),
            UnionRule(CitrusFruit, Orange),
            UnionRule(Vegetable, Zucchini),
            UnionRule(StarchyTubers, Potato),
        ]
    )

    assert union_membership == UnionMembership(
        {
            Fruit: FrozenOrderedSet([Strawberry, Apple]),
            TropicalFruit: FrozenOrderedSet([Mango, Strawberry, Apple]),
            CitrusFruit: FrozenOrderedSet([Orange, Strawberry, Apple, Mango]),
            Vegetable: FrozenOrderedSet([Zucchini]),
            StarchyTubers: FrozenOrderedSet([Potato, Zucchini]),
        }
    )
