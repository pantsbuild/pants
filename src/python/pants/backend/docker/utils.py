# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import difflib
import os.path
import re
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Callable, Iterable, Iterator, Sequence, TypeVar

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

    def to_dict(
        self, default: Callable[[str], str | None] = lambda x: None
    ) -> dict[str, str | None]:
        return {
            key: value if has_value else default(key)
            for key, has_value, value in [pair.partition("=") for pair in self]
        }


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

    def reference(path: str) -> None:
        """Track which actual files has been referenced either explicitly by a tentative path, or as
        a suggested rename."""
        if path in actual_dirs:
            referenced[path] = True
        else:
            dirname = os.path.dirname(path)
            refs = referenced.setdefault(dirname, set())
            if isinstance(refs, set):
                refs.add(path)

        # Recalculate possible matches, to avoid suggesting the same file twice.
        nonlocal actual_paths
        actual_paths = tuple(get_unreferenced(actual_files, actual_dirs))

    def is_referenced(path: str, dirname: str | None = None) -> bool:
        """Check the list of referenced files to see if `path` has been flagged.

        Walks up the directory tree in case there is a recursive flag on one of the parent
        directories.
        """
        if dirname is None:
            dirname = os.path.dirname(path)
        refs = referenced.get(dirname, set())
        if isinstance(refs, bool):
            return refs
        if path in refs:
            return True
        parentdir = os.path.dirname(dirname)
        if parentdir:
            return is_referenced(path, parentdir)
        return False

    def get_unreferenced(files: Sequence[str] = (), dirs: Sequence[str] = ()) -> Iterator[str]:
        unreferenced_files = tuple(path for path in files if not is_referenced(path))
        yield from unreferenced_files
        for path in dirs:
            if not any(filename.startswith(path + "/") for filename in unreferenced_files):
                # Skip paths where we don't have any unreferenced files any longer.
                continue
            if not is_referenced(path, path):
                yield path

    def get_matches(path: str) -> tuple[str, ...]:
        is_pattern = any(all(c in path for c in cs) for cs in ["*", "?", "[]"])
        if not is_pattern:
            return (path,) if path in actual_paths else ()
        #
        # NOTICE: There is a slight difference in the pattern syntax used for the Dockerfile `COPY`
        # instruction, than what is implemented by the `fnmatch` function in Python.
        # https://docs.docker.com/engine/reference/builder/#copy which is implemented using
        # https://golang.org/pkg/path/filepath#Match compared to
        # https://docs.python.org/3/library/fnmatch.html#fnmatch.fnmatch
        #
        # For best experience when using globs, this should be addressed, but for now, I'll settle
        # for a "close enough" approximation to get this moving.
        return tuple(p for p in actual_paths if fnmatch(p, path))

    # Go over exact matches first, so we don't target them as possible matches for renames.
    unmatched_paths = set()
    for path in tentative_paths:
        matches = get_matches(path)
        for match in matches:
            reference(match)
        if not matches:
            unmatched_paths.add(path)

    # List unknown files, possibly with a rename suggestion.
    for path in sorted(unmatched_paths):
        for suggestion in difflib.get_close_matches(path, actual_paths, n=1, cutoff=0.1):
            # Suggest rename to match what files there are.
            reference(suggestion)
            yield path, suggestion
            break
        else:
            # No match for this path.
            yield path, ""

    # List unused files.
    for path in sorted(get_unreferenced(actual_files)):
        yield "", path


def format_rename_suggestion(src_path: str, dst_path: str, *, colors: bool) -> str:
    """Given two paths, formats a line showing what to change in `src_path` to get to `dst_path`."""
    color = MaybeColor(colors)
    rem = color.maybe_red(src_path)
    add = color.maybe_green(dst_path)
    return f"{rem} => {add}"


@dataclass
class DockerImageRef:
    """See Docker image reference parsing code at github:

    https://github.com/distribution/distribution/blob/main/reference/reference.go
    """

    image: str
    tag: str | None = None
    digest: str | None = None
    name: str | None = None
    platform: str | None = None
    registry: str | None = None

    def __post_init__(self):
        name_parts = self.image.split("/")
        if self.registry:
            if len(name_parts) < 2 and ":" not in self.registry:
                self.image = f"{self.registry}/{self.image}"
                self.registry = None
        else:
            if len(name_parts) > 2 or ":" in name_parts[0]:
                self.registry = name_parts[0]
                self.image = "/".join(name_parts[1:])
                assert self.image, f"Bad image ref: {self.registry!r}"

    @property
    def image_tag(self) -> str:
        if self.tag:
            return self.tag
        if self.digest:
            return self.digest.split(":", 1)[-1]
        return "latest"

    @property
    def target_name(self) -> str:
        return self.name or "/".join(
            [s.replace(":", "_") for s in [self.registry, self.image] if s]
        )

    def __str__(self) -> str:
        def _parts():
            if self.platform:
                yield f"--platform={self.platform} "

            image = self.image
            if self.registry:
                image = "/".join([self.registry, self.image])
            if self.tag:
                image += f":{self.tag}"
            if self.digest:
                image += f"@{self.digest}"

            yield image

            if self.name:
                yield f" AS {self.name}"

        return "".join(_parts())


class DockerImageRefParser:
    def __init__(self):
        self._image_ref_pattern = re.compile(
            r"""
            ^
            # optional platform
            (--platform=(?P<platform>\S+)\s+)?
            # optional registry
            ((?P<registry>[^/:_ ]+:?[^/:_ ]*)/)?
            # image
            (?P<image>[^:@ \t\n\r\f\v]+)
            # optionally with :tag
            (:(?P<tag>[^@ ]+))?
            # optionally with @digest
            (@(?P<digest>\S+))?
            # optional name
            (\s+[Aa][Ss]\s+(?P<name>\S+))?
            $
            """,
            re.VERBOSE,
        )

    def parse(self, image_ref: str) -> DockerImageRef:
        m = self._image_ref_pattern.match(image_ref)
        if not m:
            raise ValueError(f"Invalid Docker image: {image_ref!r}")

        return DockerImageRef(**m.groupdict())
