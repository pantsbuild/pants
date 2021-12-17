# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import difflib
import os.path
from typing import Iterable, Iterator, Sequence, TypeVar

from pants.help.maybe_color import MaybeColor
from pants.util.ordered_set import FrozenOrderedSet

_T = TypeVar("_T", bound="KeyValueSequenceUtil")


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


def suggest_renames(
    tentative_paths: Iterable[str], actual_files: Sequence[str], actual_dirs: Sequence[str]
) -> Iterator[tuple[str, str]]:
    """Return each pair of `tentative_paths` matched to the best possible match of `actual_paths`
    that are not an exact match.

    A pair of `(tentative_path, "")` means there were no possible match to find in the
    `actual_paths`, while a pair of `("", actual_path)` indicates a file in the build context that
    is not taking part in any `COPY` instruction.
    """

    actual_paths = (*actual_files, *actual_dirs)
    referenced: dict[str, set[str] | bool] = {}

    def reference(path: str, *, recursive: bool) -> None:
        """Track which actual files has been referenced either explicitly by a tentative path, or as
        a suggested rename.

        The `recursive` flag indicates whether to flag all child nodes of the directory `path` as
        referenced.
        """
        if path in actual_dirs:
            if recursive:
                referenced[path] = True
            else:
                referenced[path] = {p for p in actual_files if os.path.dirname(p) == path}
        else:
            dirname = os.path.dirname(path)
            refs = referenced.setdefault(dirname, set())
            if isinstance(refs, set):
                refs.add(path)

    def is_referenced(path: str) -> bool:
        """Check the list of referenced files to see if `path` has been flagged.

        Walks up the directory tree in case there is a recursive flag on one of the parent
        directories.
        """
        dirname = os.path.dirname(path)
        refs = referenced.get(dirname, set())
        if isinstance(refs, bool):
            return refs
        if path in refs:
            return True
        if dirname:
            return is_referenced(dirname)
        return False

    # List unknown files, possibly with a rename suggestion.
    for path in tentative_paths:
        recursive = True
        if path in actual_paths:
            # Match, no need rename.
            reference(path, recursive=recursive)
            continue
        for suggestion in difflib.get_close_matches(path, actual_paths, n=1, cutoff=0.1):
            # Suggest rename to match what files there are.
            reference(suggestion, recursive=recursive)
            yield path, suggestion
            break
        else:
            # No match for this path.
            yield path, ""

    # List unused files.
    for path in actual_files:
        if not is_referenced(path):
            yield "", path


def format_rename_suggestion(src_path: str, dst_path: str, *, colors: bool) -> str:
    """Given two paths, formats a line showing what to change in `src_path` to get to `dst_path`."""
    color = MaybeColor(colors)
    matcher = difflib.SequenceMatcher(None, src_path, dst_path)
    parts = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(dst_path[j1:j2])
        elif tag in ["replace", "delete", "insert"]:
            rem = color.maybe_red(src_path[i1:i2])
            add = color.maybe_green(dst_path[j1:j2])
            parts.append(f"{{{rem} => {add}}}")
    return "".join(parts)
