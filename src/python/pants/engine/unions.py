# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, DefaultDict, Generic, Iterable, Mapping, TypeVar, cast, overload

from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_method
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet

_T = TypeVar("_T", bound=type)


@overload
def union(cls: _T, *, in_scope_types: None = None) -> _T: ...


@overload
def union(cls: None = None, *, in_scope_types: list[type]) -> Callable[[_T], _T]: ...


def union(
    cls: _T | None = None, *, in_scope_types: list[type] | None = None
) -> Callable[[_T], _T] | _T:
    """A class decorator to allow a class to be a union base in the engine's mechanism for
    polymorphism.

    Annotating a class with @union allows other classes to register a `UnionRule(BaseClass,
    MemberClass)`. Then, you can use `await Get(Output, UnionBase, concrete_union_member)`. This
    would be similar to writing `UnionRule(Output, ConcreteUnionMember,
    concrete_union_member_instance)`, but allows you to write generic code without knowing what
    concrete classes might later implement that union.

    Often, union bases are abstract classes, but they need not be.

    By default, in order to provide a stable extension API, when a `@union` is used in a `Get`,
    _only_ the provided parameter is available to callees, But in order to expand its API, a
    `@union` declaration may optionally include additional "in_scope_types", which are types
    which must already be in scope at callsites where the `@union` is used in a `Get`, and
    which are propagated to the callee.

    See https://www.pantsbuild.org/docs/rules-api-unions.
    """

    def decorator(cls: _T) -> _T:
        assert isinstance(cls, type)
        setattr(cls, "_is_union_for", cls)
        # TODO: this should involve an explicit interface soon, rather than one being implicitly
        # created with only the provided Param.
        setattr(cls, "_union_in_scope_types", tuple(in_scope_types) if in_scope_types else tuple())
        return cls

    return decorator if cls is None else decorator(cls)


def is_union(input_type: type) -> bool:
    """Return whether or not a type has been annotated with `@union`.

    This function is also implemented in Rust as `engine::externs::is_union`.
    """
    is_union: bool = input_type == getattr(input_type, "_is_union_for", None)
    return is_union


def union_in_scope_types(input_type: type) -> tuple[type, ...] | None:
    """If the given type is a `@union`, return its declared in-scope types.

    This function is also implemented in Rust as `engine::externs::union_in_scope_types`.
    """
    if not is_union(input_type):
        return None
    return cast("tuple[type, ...]", getattr(input_type, "_union_in_scope_types"))


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


@dataclass(frozen=True)
class UnionMembership:
    union_rules: FrozenDict[type, FrozenOrderedSet[type]]

    @classmethod
    def from_rules(cls, rules: Iterable[UnionRule]) -> UnionMembership:
        mapping: DefaultDict[type, OrderedSet[type]] = defaultdict(OrderedSet)
        for rule in rules:
            mapping[rule.union_base].add(rule.union_member)

        return cls(mapping)

    def __init__(self, union_rules: Mapping[type, Iterable[type]]) -> None:
        object.__setattr__(
            self,
            "union_rules",
            FrozenDict({base: FrozenOrderedSet(members) for base, members in union_rules.items()}),
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


@dataclass(frozen=True)
class _DistinctUnionTypePerSubclassGetter(Generic[_T]):
    _class: _T
    _in_scope_types: list[type] | None

    @memoized_method
    def _make_type_copy(self, objtype: type) -> _T:
        cls = self._class

        nu_type = cast(
            _T,
            type(
                cls.__name__,
                cls.__bases__,
                # NB: Override `__qualname__` so the attribute path is easily identifiable
                dict(cls.__dict__, __qualname__=f"{objtype.__qualname__}.{cls.__name__}"),
            ),
        )
        return union(in_scope_types=self._in_scope_types)(nu_type)  # type: ignore[arg-type]

    def __get__(self, obj: object | None, objtype: Any) -> _T:
        if objtype is None:
            objtype = type(obj)
        return self._make_type_copy(objtype)


@overload
def distinct_union_type_per_subclass(cls: _T, *, in_scope_types: None = None) -> _T: ...


@overload
def distinct_union_type_per_subclass(
    cls: None = None, *, in_scope_types: list[type]
) -> Callable[[_T], _T]: ...


def distinct_union_type_per_subclass(
    cls: _T | None = None, *, in_scope_types: list[type] | None = None
) -> _T | Callable[[_T], _T]:
    """Makes the decorated inner-class have a distinct, yet identical, union type per subclass.

    >>> class Foo:
    ...   @distinct_union_type_per_subclass
    ...   class Bar(cls):
    ...      pass
    ...
    >>> class Oof(Foo):
    ...   pass
    ...
    >>> Foo.Bar is not Oof.Bar
    True

    NOTE: In order to make identical class types, this should be used first of all decorators.
    NOTE: This works by making a "copy" of the class for each subclass. YMMV on how well this
        interacts with other decorators.
    """

    def decorator(cls: type):
        return _DistinctUnionTypePerSubclassGetter(cls, in_scope_types)

    return decorator if cls is None else decorator(cls)
