# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Protocol, Type

import pytest

from pants.engine.unions import UnionMembership, UnionRule, union  # , UnionRule2
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


def test_unions_using_protocols() -> None:
    class Base(Protocol):
        def frobnicate(self) -> bool:
            ...

    class A:
        def frobnicate(self) -> bool:
            return False

    class B:
        def frobnicate(self) -> bool:
            return True

    class C:
        pass

    class Base2(Protocol):
        pass

    union_membership = UnionMembership.from_rules(
        [
            UnionRule(Base, A),
            UnionRule(Base, B),
            UnionRule(Base, C),
        ]
    )
    assert union_membership == UnionMembership({Base: FrozenOrderedSet([A, B, C])})

    assert union_membership.has_members(Base)
    assert not union_membership.has_members(Base2)
    assert union_membership.is_member(Base, A())
    with pytest.raises(TypeError):
        union_membership.is_member(Base2, A())

    a: Base = A()
    b: Base = B()

    # expected type error, as C does not fulfill the Base protocol
    c: Base = C()  # type: ignore[assignment]

    assert isinstance(a, A)
    assert isinstance(b, B)
    assert isinstance(c, C)

    T: Type[Base] = A
    t = T()

    assert isinstance(t, A)

    # WIP: want typecheck to err on the following:
    # UnionRule2(Base, C)
