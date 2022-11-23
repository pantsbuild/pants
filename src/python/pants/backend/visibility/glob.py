# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Pattern

from pants.util.strutil import softwrap


class PathGlobAnchorMode(Enum):
    PROJECT_ROOT = "//"
    DECLARED_PATH = "/"
    INVOKED_PATH = "."
    FLOATING = ""

    @classmethod
    def parse(cls, pattern: str) -> PathGlobAnchorMode:
        for mode in cls.__members__.values():
            if pattern.startswith(mode.value):
                return mode
        raise TypeError("Internal Error: should not get here, please file a bug report!")


@dataclass(frozen=True)
class PathGlob:
    raw: str
    anchor_mode: PathGlobAnchorMode = field(compare=False)
    glob: Pattern = field(compare=False)

    def __str__(self) -> str:
        if self.anchor_mode is PathGlobAnchorMode.INVOKED_PATH and self.raw:
            return f"./{self.raw}"
        elif self.anchor_mode is PathGlobAnchorMode.DECLARED_PATH:
            return self.raw
        else:
            return f"{self.anchor_mode.value}{self.raw}"

    @classmethod
    def parse(cls, pattern: str, base: str) -> PathGlob:
        if not isinstance(pattern, str):
            raise ValueError(f"invalid path glob, expected string but got: {pattern!r}")
        anchor_mode = PathGlobAnchorMode.parse(pattern)
        glob = os.path.normpath(pattern).lstrip("./")
        if anchor_mode is PathGlobAnchorMode.DECLARED_PATH:
            glob = os.path.join(base, glob)
        return cls(
            raw=glob,
            anchor_mode=anchor_mode,
            glob=cls._parse_pattern(glob),
        )

    @staticmethod
    def _parse_pattern(pattern: str) -> Pattern:
        # Escape regexp characters, then restore any `*`s.
        glob = re.escape(pattern).replace(r"\*", "*")
        # Translate recursive `**` globs to regexp, a `/` prefix is optional.
        glob = glob.replace("/**", "(/.<<$>>)?")
        glob = glob.replace("**", ".<<$>>")
        # Translate `*` to match any path segment.
        glob = glob.replace("*", "[^/]<<$>>")
        # Restore `*`s that was "escaped" during translation.
        glob = glob.replace("<<$>>", "*")
        # Return regexp for translated glob pattern.
        return re.compile(glob + "$")

    def _match_path(self, path: str, base: str) -> str | None:
        if self.anchor_mode is PathGlobAnchorMode.INVOKED_PATH:
            path = os.path.relpath(path, base)
            if path.startswith(".."):
                # The `path` is not in the sub tree of `base`.
                return None
        return path.lstrip(".")

    def match(self, path: str, base: str) -> bool:
        match_path = self._match_path(path, base)
        return (
            False
            if match_path is None
            else bool(
                (re.search if self.anchor_mode is PathGlobAnchorMode.FLOATING else re.match)(
                    self.glob, match_path
                )
            )
        )


@dataclass(frozen=True)
class TargetGlob:
    type_: str | None
    path: PathGlob | None
    tags: tuple[str, ...] | None

    def __post_init__(self) -> None:
        if not isinstance(self.type_, (str, type(None))):
            raise ValueError(f"invalid target type, expected glob but got: {self.type_!r}")
        if not isinstance(self.path, (PathGlob, type(None))):
            raise ValueError(f"invalid target path, expected glob but got: {self.path!r}")
        if not isinstance(self.tags, (tuple, type(None))):
            raise ValueError(
                f"invalid target tags, expected sequence of values but got: {self.tags!r}"
            )

    def __str__(self) -> str:
        # Note: when there are more selection criteria used than is supported as a single text
        # value, switch over to a dict based representation.
        tags = (
            f"({', '.join(str(tag) if ',' not in tag else repr(tag) for tag in self.tags)})"
            if self.tags is not None
            else ""
        )
        path = f"[{self.path}]" if self.path is not None else ""
        return f"{self.type_ or ''}{tags}{path}" or "*"

    @classmethod
    def parse(cls, spec: str | Mapping[str, Any], relpath: str) -> TargetGlob:
        if isinstance(spec, str):
            spec_dict = cls._parse_string(spec)
            from pprint import pprint

            pprint(spec_dict)
        elif isinstance(spec, Mapping):
            spec_dict = spec
        else:
            raise ValueError(f"invalid target spec, expected string or dict but got: {spec!r}")

        return cls(
            type_=spec_dict.get("type"),
            path=PathGlob.parse(spec_dict["path"], relpath)
            if spec_dict.get("path") is not None
            else None,
            tags=cls._parse_tags(spec_dict.get("tags")),
        )

    @staticmethod
    def _parse_string(spec: str) -> Mapping[str, Any]:
        match = re.match(
            r"""
            (?P<type>[^([]*)
            (?:
              \(
                (?P<tags>[^)]*)
              \)
            )?
            (?:
              \[
                (?P<path>[^]]*)
              \]
            )?
            $
            """,
            spec,
            re.VERBOSE,
        )
        if not match:
            raise ValueError(
                f"invalid target spec string with optional parts of 'target-glob(tag-value, ...)[path-glob]' "
                f"but got: {spec!r}"
            )
        print(match, match.groups())
        return match.groupdict()

    @staticmethod
    def _parse_tags(tags: str | Sequence[str] | None) -> tuple[Any, ...] | None:
        if tags is None:
            return None
        if isinstance(tags, str):
            if "'" in tags or '"' in tags:
                raise ValueError(
                    softwrap(
                        f"""
                        Quotes not supported for tags rule selector in string form, quotes only
                        needed for tag values with commas in them otherwise simply remove the
                        quotes. For embedded commas, use the dictionary syntax:

                          {{"tags": [{tags!r}, ...], ...}}
                        """
                    )
                )
            tags = tags.split(",")
        if not isinstance(tags, Sequence):
            raise ValueError(
                f"invalid tags, expected a tag or a list of tags but got: {type(tags).__name__}"
            )
        tags = tuple(str(tag).strip() for tag in tags)
        return tags
