# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import TypeVar

from pants.util.ordered_set import FrozenOrderedSet

_T = TypeVar("_T", bound="KeyValueSequenceUtil")


class KeyValueSequenceUtil(FrozenOrderedSet[str]):
    @classmethod
    def from_strings(cls: type[_T], *strings: str) -> _T:
        """Takes all `KEY`/`KEY=VALUE` strings and dedupes by `KEY`.

        The last seen `KEY` wins in case of duplicates.
        """

        key_to_entry: dict[str, str] = {}
        for entry in strings:
            # Note that last entry with the same key wins.
            key_to_entry[entry.partition("=")[0]] = entry
        deduped_entries = sorted(key_to_entry.values())

        return cls(FrozenOrderedSet(deduped_entries))
