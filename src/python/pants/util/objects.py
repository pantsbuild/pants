# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABC, abstractmethod
from textwrap import dedent
from typing import Any, Iterable, Optional, Type, Union


def get_docstring_summary(
    cls: Type, *, fallback_to_ancestors: bool = False, ignored_ancestors: Iterable[Type] = (object,)
) -> Optional[str]:
    """Get the summary line(s) of docstring for a class.

    If the summary is one more than one line, this will flatten them into a single line.
    """
    # This will fix indentation and strip unnecessary whitespace.
    all_docstring = get_docstring(
        cls, fallback_to_ancestors=fallback_to_ancestors, ignored_ancestors=ignored_ancestors
    )

    if all_docstring is None:
        return None

    lines = all_docstring.splitlines()
    first_blank_line_index = next(
        (i for i, line in enumerate(lines) if line.strip() == ""), len(lines)
    )
    return " ".join(lines[:first_blank_line_index])


def get_docstring(
    cls: Type,
    *,
    flatten: bool = False,
    fallback_to_ancestors: bool = False,
    ignored_ancestors: Iterable[Type] = (object,),
) -> Optional[str]:
    """Get the docstring for a class with properly handled indentation.

    :param cls: the class, e.g. MyClass.
    :param flatten: flatten the docstring into a single line by replacing all newlines with spaces
        and stripping leading indentation.
    :param fallback_to_ancestors: if the class does not have docstring defined, try to use docstring
        from its superclasses, if any. This traverses in the MRO order, i.e. tries to use its
        direct parent, then grandparent, and ultimately `object()`.
    :param ignored_ancestors: if `fallback_to_ancestors` is True, do not use the docstring from
        these ancestors.
    """
    if cls.__doc__ is not None:
        docstring = cls.__doc__.strip()
    else:
        if not fallback_to_ancestors:
            return None
        # Fallback to ancestors in MRO order.
        ancestor_docstring = next(
            (
                ancestor_cls.__doc__.strip()
                for ancestor_cls in cls.mro()[1:]
                if ancestor_cls not in ignored_ancestors and ancestor_cls.__doc__ is not None
            ),
            None,
        )
        if ancestor_docstring is None:
            return None
        docstring = ancestor_docstring

    newline_index = docstring.find("\n")
    if newline_index == -1:
        return docstring

    # Fix indentation of lines after the first line.
    lines = [docstring[:newline_index], *dedent(docstring[newline_index + 1 :]).splitlines()]

    if flatten:
        return " ".join(line.strip() for line in lines if line).strip()
    return "\n".join(lines)


def pretty_print_type_hint(hint: Any) -> str:
    if getattr(hint, "__origin__", None) == Union:
        union_members = hint.__args__
        hint_str = f" | ".join(pretty_print_type_hint(member) for member in union_members)
    # NB: Checking for GenericMeta is only for Python 3.6 because some `typing` classes like
    # `typing.Iterable` have its type, whereas Python 3.7+ removes it. Remove this check
    # once we drop support for Python 3.6.
    elif isinstance(hint, type) and not str(type(hint)) == "<class 'typing.GenericMeta'>":
        hint_str = hint.__name__
    else:
        hint_str = str(hint)
    return hint_str.replace("typing.", "").replace("NoneType", "None")


# TODO: make this error into an attribute on the `TypeConstraint` class object!
class TypeConstraintError(TypeError):
    """Indicates a :class:`TypeConstraint` violation."""


class TypeConstraint(ABC):
    """Represents a type constraint.

    Not intended for direct use; instead, use one of :class:`SuperclassesOf`, :class:`Exactly` or
    :class:`SubclassesOf`.
    """

    def __init__(self, description):
        """Creates a type constraint centered around the given types.

        The type constraint is satisfied as a whole if satisfied for at least one of the given types.

        :param str description: A concise, readable description of what the type constraint represents.
                                Used directly as the __str__ implementation.
        """
        self._description = description

    @abstractmethod
    def satisfied_by(self, obj):
        """Return `True` if the given object satisfies this type constraint.

        :rtype: bool
        """

    def make_type_constraint_error(self, obj, constraint):
        return TypeConstraintError(
            "value {!r} (with type {!r}) must satisfy this type constraint: {}.".format(
                obj, type(obj).__name__, constraint
            )
        )

    # TODO: disallow overriding this method with some form of mixin/decorator along with datatype
    # __eq__!
    def validate_satisfied_by(self, obj):
        """Return `obj` if the object satisfies this type constraint, or raise.

        :raises: `TypeConstraintError` if `obj` does not satisfy the constraint.
        """

        if self.satisfied_by(obj):
            return obj

        raise self.make_type_constraint_error(obj, self)

    def __ne__(self, other):
        return not (self == other)

    def __str__(self):
        return self._description


class TypeOnlyConstraint(TypeConstraint):
    """A `TypeConstraint` predicated only on the object's type.

    `TypeConstraint` subclasses may override `.satisfied_by()` to perform arbitrary validation on
    the object itself -- however, this class implements `.satisfied_by()` with a guarantee that it
    will only act on the object's `type` via `.satisfied_by_type()`. This kind of type checking is
    faster and easier to understand than the more complex validation allowed by `.satisfied_by()`.
    """

    def __init__(self, *types):
        """Creates a type constraint based on some logic to match the given types.

        NB: A `TypeOnlyConstraint` implementation should ensure that the type constraint is satisfied as
        a whole if satisfied for at least one of the given `types`.

        :param type *types: The types this constraint will match in some way.
        """

        if not types:
            raise ValueError("Must supply at least one type")
        if any(not isinstance(t, type) for t in types):
            raise TypeError(f"Supplied types must be types. {types!r}")

        if len(types) == 1:
            type_list = types[0].__name__
        else:
            type_list = " or ".join(t.__name__ for t in types)
        description = f"{type(self).__name__}({type_list})"

        super().__init__(description=description)

        # NB: This is made into a tuple so that we can use self._types in issubclass() and others!
        self._types = tuple(types)

    # TODO(#7114): remove this after the engine is converted to use `TypeId` instead of
    # `TypeConstraint`!
    @property
    def types(self):
        return self._types

    @abstractmethod
    def satisfied_by_type(self, obj_type):
        """Return `True` if the given object satisfies this type constraint.

        :rtype: bool
        """

    def satisfied_by(self, obj):
        return self.satisfied_by_type(type(obj))

    def __hash__(self):
        return hash((type(self), self._types))

    def __eq__(self, other):
        return type(self) == type(other) and self._types == other._types

    def __repr__(self):
        constrained_type = ", ".join(t.__name__ for t in self._types)
        return f"{type(self).__name__}({constrained_type})"


class SuperclassesOf(TypeOnlyConstraint):
    """Objects of the exact type as well as any super-types are allowed."""

    def satisfied_by_type(self, obj_type):
        return any(issubclass(t, obj_type) for t in self._types)


class Exactly(TypeOnlyConstraint):
    """Only objects of the exact type are allowed."""

    def satisfied_by_type(self, obj_type):
        return obj_type in self._types

    def graph_str(self):
        if len(self.types) == 1:
            return self.types[0].__name__
        else:
            return repr(self)


class SubclassesOf(TypeOnlyConstraint):
    """Objects of the exact type as well as any sub-types are allowed."""

    def satisfied_by_type(self, obj_type):
        return issubclass(obj_type, self._types)
