# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.unions import UnionMembership, UnionRule, union
from pants.util.ordered_set import FrozenOrderedSet


def test_union_membership_from_rules() -> None:
    @union
    class Base:
        pass

    class A:
        pass

    class B:
        pass

    assert UnionMembership.from_rules([UnionRule(Base, A), UnionRule(Base, B)]) == UnionMembership(
        {Base: FrozenOrderedSet([A, B])}
    )
