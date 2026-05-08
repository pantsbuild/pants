# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar, cast, overload

from pants.engine.internals.native_engine import (  # noqa: F401 # re-export
    UnionMembership as UnionMembership,
)
from pants.engine.internals.native_engine import UnionRule as UnionRule  # noqa: F401 # re-export
from pants.util.memo import memoized_method

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
    MemberClass)`. Then, given

    @rule(polymorphic=True)
    async def base_rule(arg: BaseClass) -> Output:
       raise NotImplementedError()

    and

    @rule
    async def member_rule(arg: MemberClass) -> Output:
        ....

    Then `await base_rule(**implicitly({member_class_instance: MemberClass}))` will dispatch
    to member_rule() at runtime based on the type of the argument.

    This allows you to write generic code without knowing what concrete classes might later
    implement that union.

    Often, union bases are abstract classes, and the members subclass the base, but this need not
    be the case.

    By default, in order to provide a stable extension API, when a `@union` is used in a @rule
    _only_ the provided parameter is available to callees, But in order to expand its API, a
    `@union` declaration may optionally include additional "in_scope_types", which are types
    which must already be in scope at callsites where the `@union` is used, and
    which are propagated to the callee, which must have an argument of that type.

    See https://www.pantsbuild.org/stable/docs/writing-plugins/the-rules-api/union-rules-advanced.
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
