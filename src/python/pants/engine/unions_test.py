# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Protocol, runtime_checkable

import pytest

from pants.engine.unions import UnionBase, UnionMembership, UnionRule, union
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
    # Setup different versions of Union base classes, show casing UnionBase vs Protocol (w/ and w/o
    # @runtime_checkable).

    class Base(UnionBase):
        def frobnicate(self) -> bool:
            ...

    # This will be the line to go with, using Protocol directly. The runtime_checkable decorator
    # could be made optional, especially if using attributes, which it is not compatible with.. I
    # was hoping for something cleaner, but maybe not too bad, considering the hackish workarounds
    # required to make it work otherwise.
    @runtime_checkable
    class Base2(Protocol):
        def some(self) -> str:
            ...

    class Base3(Protocol):
        pass

    class Base4(Protocol):
        attr: int

    # All bases of a Protocol must be protocols.. so we tripped up here, with the UnionBase.
    class Derived(Base, Protocol):  # type: ignore[misc]
        def gonk(self) -> None:
            ...

    class Derived2(Base2, Protocol):
        def other(self) -> float:
            ...

    class A:
        def frobnicate(self) -> bool:
            return False

    class B:
        def some(self) -> str:
            return "thing"

        def frobnicate(self) -> bool:
            return True

    class C:
        def some(self) -> str:
            return "thing"

    class D(A, C):
        def gonk(self) -> None:
            return None

        def other(self) -> float:
            return 1.2

    union_membership = UnionMembership.from_rules(
        [
            UnionRule(Base, A),
            UnionRule(Base, B),
            UnionRule(Base2, B),
            UnionRule(Base2, C),
            UnionRule(Derived, D),
            UnionRule(Derived2, D),
        ]
    )
    assert union_membership == UnionMembership(
        {
            Base: FrozenOrderedSet([A, B]),
            Base2: FrozenOrderedSet([B, C]),
            Derived: FrozenOrderedSet([D]),
            Derived2: FrozenOrderedSet([D]),
        }
    )

    assert union_membership.has_members(Base)
    assert not union_membership.has_members(UnionBase)
    assert union_membership.is_member(Base, A())
    assert not union_membership.is_member(Base2, A())
    with pytest.raises(TypeError):
        union_membership.is_member(UnionBase, A())

    # wanted typecheck to err on the following, but didn't manage that, so settled to have a runtime
    # check instead.
    with pytest.raises(ValueError):
        # Not OK - C does not fulfill the Base protocol
        UnionRule(Base, C)

    with pytest.raises(ValueError):
        # Not OK - Base3 is not runtime checkable
        UnionRule(Base3, C)

    # Type check tests, with UnionBase vs clean Protocol classes

    # mypy does not pick up our trick to turn Base into a Protocol, so this is not OK
    a: Base = A()  # type: ignore[assignment]

    # Base2 and Base3 are both explicitly Protocols, so this is OK
    b: Base2 = B()
    c: Base3 = C()

    # C does not fulfill Base4, so this is not OK
    d: Base4 = C()  # type: ignore[assignment]
    # error: Incompatible types in
    # assignment (expression has type "C", variable has type "Base4")  [assignment]
    #    d: Base4 = C()
    #               ^

    assert a and b and c and d
