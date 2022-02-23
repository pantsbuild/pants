# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Iterable, Mapping, TypeVar

from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


def union(cls):
    """A class decorator to allow a class to be a union base in the engine's mechanism for
    polymorphism.

    Annotating a class with @union allows other classes to register a `UnionRule(BaseClass,
    MemberClass)`. Then, you can use `await Get(Output, UnionBase, concrete_union_member)`. This
    would be similar to writing `UnionRule(Output, ConcreteUnionMember,
    concrete_union_member_instance)`, but allows you to write generic code without knowing what
    concrete classes might later implement that union.

    Often, union bases are abstract classes, but they need not be.

    See https://www.pantsbuild.org/docs/rules-api-unions.
    """
    assert isinstance(cls, type)
    cls._is_union_for = cls
    return cls


def is_union(input_type: type) -> bool:
    """Return whether or not a type has been annotated with `@union`."""
    is_union: bool = input_type == getattr(input_type, "_is_union_for", None)
    return is_union


@dataclass(frozen=True)
class UnionRule:
    """Specify that an instance of `union_member` can be substituted wherever `union_base` is
    used."""

    union_base: type
    union_member: type

    def __post_init__(self) -> None:
        if not is_union(self.union_base):
            msg = (
                f"The first argument must be a class annotated with @union "
                f"(from pants.engine.unions), but was {self.union_base}."
            )
            if is_union(self.union_member):
                msg += (
                    "\n\nHowever, the second argument was annotated with `@union`. Did you "
                    "switch the first and second arguments to `UnionRule()`?"
                )
            raise ValueError(msg)


_T = TypeVar("_T", bound=type)


@frozen_after_init
@dataclass(unsafe_hash=True)
class UnionMembership:
    union_rules: FrozenDict[type, FrozenOrderedSet[type]]

    @classmethod
    def from_rules(cls, rules: Iterable[UnionRule]) -> UnionMembership:
        mapping: DefaultDict[type, OrderedSet[type]] = defaultdict(OrderedSet)
        for rule in rules:
            mapping[rule.union_base].add(rule.union_member)
        return cls(mapping)

    def __init__(self, union_rules: Mapping[type, Iterable[type]]) -> None:
        self.union_rules = FrozenDict(
            {base: FrozenOrderedSet(members) for base, members in union_rules.items()}
        )

    def __contains__(self, union_type: _T) -> bool:
        return union_type in self.union_rules

    def __getitem__(self, union_type: _T) -> FrozenOrderedSet[_T]:
        """Get all members of this union type.

        If the union type does not exist because it has no members registered, this will raise an
        IndexError.

        Note that the type hint assumes that all union members will have subclassed the union type
        - this is only a convention and is not actually enforced. So, you may have inaccurate type
        hints.
        """
        return self.union_rules[union_type]  # type: ignore[return-value]

    def get(self, union_type: _T) -> FrozenOrderedSet[_T]:
        """Get all members of this union type.

        If the union type does not exist because it has no members registered, return an empty
        FrozenOrderedSet.

        Note that the type hint assumes that all union members will have subclassed the union type
        - this is only a convention and is not actually enforced. So, you may have inaccurate type
        hints.
        """
        return self.union_rules.get(union_type, FrozenOrderedSet())  # type: ignore[return-value]

    def is_member(self, union_type: type, putative_member: type) -> bool:
        members = self.union_rules.get(union_type)
        if members is None:
            raise TypeError(f"Not a registered union type: {union_type}")
        return type(putative_member) in members

    def has_members(self, union_type: type) -> bool:
        """Check whether the union has an implementation or not."""
        return bool(self.union_rules.get(union_type))
