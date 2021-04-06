# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import DefaultDict, Iterable, Mapping, Type, TypeVar

from pants.util.frozendict import FrozenDict
from pants.util.meta import decorated_type_checkable, frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


@decorated_type_checkable
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
    # TODO: Check that the union base type is used as a tag and nothing else (e.g. no attributes)!
    assert isinstance(cls, type)
    return union.define_instance_of(cls)


def is_union(input_type: type) -> bool:
    """Return whether or not a type has been annotated with `@union`."""
    return union.is_instance(input_type)


@dataclass(frozen=True)
class UnionRule:
    """Specify that an instance of `union_member` can be substituted wherever `union_base` is
    used."""

    union_base: Type
    union_member: Type

    def __post_init__(self) -> None:
        if not union.is_instance(self.union_base):
            msg = (
                f"The first argument must be a class annotated with @union "
                f"(from pants.engine.unions), but was {self.union_base}."
            )
            if union.is_instance(self.union_member):
                msg += (
                    "\n\nHowever, the second argument was annotated with `@union`. Did you "
                    "switch the first and second arguments to `UnionRule()`?"
                )
            raise ValueError(msg)


_T = TypeVar("_T")


@frozen_after_init
@dataclass(unsafe_hash=True)
class UnionMembership:
    union_rules: FrozenDict[Type, FrozenOrderedSet[Type]]

    @classmethod
    def from_rules(cls, rules: Iterable[UnionRule]) -> UnionMembership:
        mapping: DefaultDict[Type, OrderedSet[Type]] = defaultdict(OrderedSet)
        for rule in rules:
            mapping[rule.union_base].add(rule.union_member)
        return cls(mapping)

    def __init__(self, union_rules: Mapping[Type, Iterable[Type]]) -> None:
        self.union_rules = FrozenDict(
            {base: FrozenOrderedSet(members) for base, members in union_rules.items()}
        )

    def __getitem__(self, union_type: Type[_T]) -> FrozenOrderedSet[Type[_T]]:
        """Get all members of this union type.

        If the union type does not exist because it has no members registered, this will raise an
        IndexError.

        Note that the type hint assumes that all union members will have subclassed the union type
        - this is only a convention and is not actually enforced. So, you may have inaccurate type
        hints.
        """
        return self.union_rules[union_type]

    def get(self, union_type: Type[_T]) -> FrozenOrderedSet[Type[_T]]:
        """Get all members of this union type.

        If the union type does not exist because it has no members registered, return an empty
        FrozenOrderedSet.

        Note that the type hint assumes that all union members will have subclassed the union type
        - this is only a convention and is not actually enforced. So, you may have inaccurate type
        hints.
        """
        return self.union_rules.get(union_type, FrozenOrderedSet())

    def is_member(self, union_type: Type, putative_member: Type) -> bool:
        members = self.union_rules.get(union_type)
        if members is None:
            raise TypeError(f"Not a registered union type: {union_type}")
        return type(putative_member) in members

    def has_members(self, union_type: Type) -> bool:
        """Check whether the union has an implementation or not."""
        return bool(self.union_rules.get(union_type))

    def has_members_for_all(self, union_types: Iterable[Type]) -> bool:
        """Check whether every union given has an implementation or not."""
        return all(self.has_members(union_type) for union_type in union_types)
