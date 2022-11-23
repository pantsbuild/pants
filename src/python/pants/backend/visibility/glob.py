# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Pattern


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
    uplvl: int

    @classmethod
    def parse(cls, pattern: str, base: str) -> PathGlob:
        anchor_mode = PathGlobAnchorMode.parse(pattern)
        glob = os.path.normpath(pattern)
        uplvl = glob.count("../")
        glob = glob.lstrip("./")
        if anchor_mode is PathGlobAnchorMode.DECLARED_PATH:
            glob = os.path.join(base, glob)
        return cls(
            raw=pattern,
            anchor_mode=anchor_mode,
            glob=cls._parse_pattern(glob),
            uplvl=uplvl,
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
            path = os.path.relpath(path, base + "/.." * self.uplvl)
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
