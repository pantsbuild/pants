# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from __future__ import annotations

import ast
from typing import TypeVar, cast

T = TypeVar("T")


def maybe_narrow_type(node: ast.expr, types: type[T] | tuple[type[T], ...]) -> T | None:
    """Narrow an AST expr to another type if it matches the expected type at runtime, or None."""
    return cast(T, node) if isinstance(node, types) else None


def narrow_type(node: ast.expr, types: type[T] | tuple[type[T], ...]) -> T:
    """Narrow an AST expr to another type if it matches the expected type at runtime, or throw.

    :raises ValueError: if the node is not an instance of the expected type.
    """
    if value := maybe_narrow_type(node, types):
        return value
    raise ValueError(f"Expected {node} to be one of {types}")
