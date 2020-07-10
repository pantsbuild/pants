# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

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
        hint_str = " | ".join(pretty_print_type_hint(member) for member in union_members)
    # NB: Checking for GenericMeta is only for Python 3.6 because some `typing` classes like
    # `typing.Iterable` have its type, whereas Python 3.7+ removes it. Remove this check
    # once we drop support for Python 3.6.
    elif isinstance(hint, type) and not str(type(hint)) == "<class 'typing.GenericMeta'>":
        hint_str = hint.__name__
    else:
        hint_str = str(hint)
    return hint_str.replace("typing.", "").replace("NoneType", "None")
