# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Any, TypeVar, cast

from pants.util.frozendict import FrozenDict

_T = TypeVar("_T")


class RunId(int):
    """A unique id for a single run or `--loop` iteration of Pants within a single Scheduler.

    RunIds are not comparable across Scheduler instances, and only equality is meaningful, not
    ordering.
    """


class SessionValues(FrozenDict[type, Any]):
    """Values set for the Session, and exposed to @rules.

    Generally, each type provided via `SessionValues` should have a simple rule that returns the
    type so that users can directly request it in a rule, rather than needing to query
    `SessionValues`.
    """

    def __getitem__(self, item: type[_T]) -> _T:
        try:
            return cast(_T, super().__getitem__(item))
        except KeyError:
            raise KeyError(f"Expected {item.__name__} to be provided via SessionValues.")
