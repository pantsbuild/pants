# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from typing import Self, TypeVar

from pants.engine.internals import native_engine
from pants.help.maybe_color import MaybeColor
from pants.util.ordered_set import FrozenOrderedSet

_T = TypeVar("_T", bound="KeyValueSequenceUtil")


image_ref_regexp = re.compile(
    r"""
    ^
    # Optional registry.
    ((?P<registry>[^/:_ ]+:?[^/:_ ]*)/)?
    # Repository.
    (?P<repository>[^:@ \t\n\r\f\v]+)
    # Optionally with `:tag`.
    (:(?P<tag>[^@ ]+))?
    # Optionally with `@digest`.
    (@(?P<digest>\S+))?
    $
    """,
    re.VERBOSE,
)


class KeyValueSequenceUtil(FrozenOrderedSet[str]):
    @classmethod
    def from_strings(cls: type[_T], *strings: str, duplicates_must_match: bool = False) -> _T:
        """Takes all `KEY`/`KEY=VALUE` strings and dedupes by `KEY`.

        The last seen `KEY` wins in case of duplicates, unless `duplicates_must_match` is `True`, in
        which case all `VALUE`s must be equal, if present.
        """

        key_to_entry_and_value: dict[str, tuple[str, str | None]] = {}
        for entry in strings:
            key, has_value, value = entry.partition("=")
            if not duplicates_must_match:
                # Note that last entry with the same key wins.
                key_to_entry_and_value[key] = (entry, value if has_value else None)
            else:
                prev_entry, prev_value = key_to_entry_and_value.get(key, (None, None))
                if prev_entry is None:
                    # Not seen before.
                    key_to_entry_and_value[key] = (entry, value if has_value else None)
                elif not has_value:
                    # Seen before, no new value, so keep existing.
                    pass
                elif prev_value is None:
                    # Update value.
                    key_to_entry_and_value[key] = (entry, value)
                elif prev_value != value:
                    # Seen before with a different value.
                    raise ValueError(
                        f"{cls.__name__}: duplicated {key!r} with different values: "
                        f"{prev_value!r} != {value!r}."
                    )

        deduped_entries = sorted(
            entry_and_value[0] for entry_and_value in key_to_entry_and_value.values()
        )
        return cls(FrozenOrderedSet(deduped_entries))

    @classmethod
    def from_dict(cls, value: dict[str, str | None]) -> Self:
        def encode_kv(k: str, v: str | None) -> str:
            if v is None:
                return k
            return "=".join((k, v))

        return cls(FrozenOrderedSet(sorted(encode_kv(k, v) for k, v in value.items())))

    def to_dict(
        self, default: Callable[[str], str | None] = lambda x: None
    ) -> dict[str, str | None]:
        return {
            key: value if has_value else default(key)
            for key, has_value, value in [pair.partition("=") for pair in self]
        }


def suggest_renames(
    tentative_paths: Iterable[str], actual_files: Sequence[str], actual_dirs: Sequence[str]
) -> list[tuple[str, str]]:
    """Return each pair of `tentative_paths` matched to the best possible match of `actual_paths`
    that are not an exact match.

    A pair of `(tentative_path, "")` means there were no possible match to find in the
    `actual_paths`, while a pair of `("", actual_path)` indicates a file in the build context that
    is not taking part in any `COPY` instruction.
    """
    return native_engine.suggest_renames(
        tuple(tentative_paths), tuple(actual_files), tuple(actual_dirs)
    )


def format_rename_suggestion(src_path: str, dst_path: str, *, colors: bool) -> str:
    """Given two paths, formats a line showing what to change in `src_path` to get to `dst_path`."""
    color = MaybeColor(colors)
    rem = color.maybe_red(src_path)
    add = color.maybe_green(dst_path)
    return f"{rem} => {add}"
