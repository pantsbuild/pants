# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import abstractmethod
from dataclasses import dataclass

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


def test_unions_using_abc() -> None:
    class CustomUnion(UnionBase):
        @abstractmethod
        def frobnicate(self) -> bool:
            # default impl
            return False

    @dataclass
    class Impl1(CustomUnion):
        prop: str
        opt: int

        # mypy catches the following mistake (wrong ret type: bool -> str)
        def frobnicate(self) -> str:  # type: ignore[override]
            return self.prop * self.opt

    union_membership = UnionMembership.from_rules(
        [
            UnionRule(CustomUnion, Impl1),
        ]
    )

    assert union_membership == UnionMembership(
        {
            CustomUnion: FrozenOrderedSet([Impl1]),
        }
    )

    a = Impl1("val", 2)
    assert a.frobnicate() == "valval"

    with pytest.raises(ValueError):
        UnionRule(Impl1, CustomUnion)
