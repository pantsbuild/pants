# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from itertools import groupby
from typing import Iterable, Type, TypeVar

from pants.util.ordered_set import FrozenOrderedSet

_T = TypeVar("_T", bound="KeyValueSequenceUtilMixin")


class KeyValueSequenceUtilMixin(FrozenOrderedSet[str]):
    @classmethod
    def from_iterables(cls: Type[_T], *iterables: Iterable[str]) -> _T:
        """Takes `KEY` or `KEY=VALUE` pairs from iterables.

        The prio is in ascending order, so the last iterable will win in case a `KEY` exists in more
        than one iterable.
        """

        def extract_key(entry: tuple[str, int]) -> str:
            pair, it_idx = entry
            return pair.partition("=")[0]

        def iterator_order(entry: tuple[str, int]) -> int:
            pair, it_idx = entry
            return it_idx

        data = sorted((pair, it_idx) for it_idx, it in enumerate(iterables) for pair in it)
        return cls(
            FrozenOrderedSet(
                sorted(
                    {
                        # Take the pair value of the last entry in the group.
                        sorted(group, key=iterator_order)[-1][0]
                        for _key, group in groupby(data, extract_key)
                    }
                )
            )
        )
