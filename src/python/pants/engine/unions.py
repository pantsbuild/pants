# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, DefaultDict, Iterable, Mapping, Protocol, Type, TypeVar, runtime_checkable

from pants.util.frozendict import FrozenDict
from pants.util.meta import decorated_type_checkable, frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


class UnionBaseMetaclass(type):
    # This trick with UnionBase just shows that it does NOT work well.
    """Turn UnionBase derived classes into runtime checkable Protocol classes.

    This trick fools mypy into not seeing the resulting class as being a Protocol, however.
    """

    def __new__(meta_cls, name, bases, namespace):
        if name == "UnionBase":
            cls = type.__new__(meta_cls, name, bases, namespace)
        else:
            meta_cls = type(Protocol)
            if Protocol not in bases:
                bases = (*bases, Protocol)

            cls = runtime_checkable(
                meta_cls.__new__(
                    meta_cls,
                    name,
                    tuple(base for base in bases if base.__name__ != "UnionBase"),
                    namespace,
                )
            )
        return cls


class UnionBase(metaclass=UnionBaseMetaclass):
    """We require runtime checkable Protocol classes.

    Deriving from this class make the user code cleaner, but does not work as regular Protocol
    classes, as mypy fails to detect them as such.
    """


@decorated_type_checkable
def union(cls):
    """A class decorator to allow a class to be a union base in the engine's mechanism for
    polymorphism.

    Annotating a class with @union allows other classes to register a `UnionRule(BaseClass,
    MemberClass)`. Then, you can use `await Get(Output, BaseClass, concrete_union_member)`. This
    would be similar to writing `Get(Output, MemberClass,
    concrete_union_member)`, but allows you to write generic code without knowing what
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
        if getattr(self.union_base, "_is_protocol", False):
            self.__check_union_protocol()
        else:
            self.__check_decorated_union()

    def __check_union_protocol(self):
        if not getattr(self.union_base, "_is_runtime_protocol", False):
            raise ValueError(
                "The first argument, {self.union_base}, must either be decorated "
                "with @typing.runtime_checkable in order to check the Union Protocol, "
                "or derive from pants.engine.unions.UnionBase."
            )

        if not issubclass(self.union_member, self.union_base):
            raise ValueError(
                f"The second argument, {self.union_member}, must satisfy the "
                f"union Protocol {self.union_base}."
            )

    def __check_decorated_union(self):
        if union.is_instance(self.union_base):
            return

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


_T = TypeVar("_T", bound=type)


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

    def is_member(self, union_type: Type, putative_member: Any) -> bool:
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
