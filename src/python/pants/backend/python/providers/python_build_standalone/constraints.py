# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import operator
from typing import Callable, Iterable, Protocol, cast

from packaging.version import Version

_OPERATORS = (
    (">=", operator.ge),
    ("<=", operator.le),
    ("==", operator.eq),
    ("!=", operator.ne),
    # `>` and `<` must come last since these strings are shorter!
    (">", operator.gt),
    ("<", operator.lt),
)


class ConstraintParseError(Exception):
    pass


class ConstraintSatisfied(Protocol):
    def is_satisified(self, version: Version) -> bool:
        ...


class Constraint(ConstraintSatisfied):
    """A single version constraint with operator."""

    def __init__(
        self, cmp_callback: Callable[[Version, Version], bool], cmp_version: Version
    ) -> None:
        self.cmp_callback: Callable[[Version, Version], bool] = cmp_callback
        self.cmp_version: Version = cmp_version

    def is_satisified(self, version: Version) -> bool:
        return self.cmp_callback(version, self.cmp_version)

    @classmethod
    def parse(cls, constraint: str) -> Constraint:
        constraint = constraint.strip()

        cmp_op_and_callback: tuple[str, Callable[[Version, Version], bool]] | None = None
        for op, callback in _OPERATORS:
            if constraint.startswith(op):
                cmp_op_and_callback = (op, cast("Callable[[Version, Version], bool]", callback))
                break

        if cmp_op_and_callback is None:
            raise ConstraintParseError(
                f"A constraint must start with a comparison operator, i.e. {', '.join(x[0] for x in _OPERATORS)}, found {constraint!r}."
            )

        cmp_op, cmp_callback = cmp_op_and_callback
        cmp_version = Version(constraint[len(cmp_op) :])
        return cls(cmp_callback, cmp_version)


class ConstraintsList(ConstraintSatisfied):
    """A list of constraints which must all match (i.e., they are AND'ed together)."""

    def __init__(self, constraints: Iterable[ConstraintSatisfied]) -> None:
        self.constraints: tuple[ConstraintSatisfied, ...] = tuple(constraints)

    def is_satisified(self, version: Version) -> bool:
        for constraint in self.constraints:
            if not constraint.is_satisified(version):
                return False
        return True

    @classmethod
    def parse(cls, constraints_str: str) -> ConstraintsList:
        parts = constraints_str.split(",")
        constraints = [Constraint.parse(part) for part in parts]
        return cls(constraints)
