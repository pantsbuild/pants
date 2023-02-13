# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import os.path
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatchcase
from typing import Any, Pattern

from pants.engine.addresses import Address
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.memo import memoized_classmethod
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
                if mode is PathGlobAnchorMode.INVOKED_PATH:
                    # Special case "invoked path", to not select ".text"; only "." "../" or "./" are
                    # valid for "invoked path" mode. (we're not picky on the number of leading dots)
                    if pattern.lstrip(".")[:1] not in ("", "/"):
                        return PathGlobAnchorMode.FLOATING
                return mode
        raise TypeError("Internal Error: should not get here, please file a bug report!")


@dataclass(frozen=True)
class PathGlob:
    raw: str
    anchor_mode: PathGlobAnchorMode = field(compare=False)
    glob: Pattern = field(compare=False)
    uplvl: int

    def __str__(self) -> str:
        if self.anchor_mode is PathGlobAnchorMode.INVOKED_PATH and self.raw:
            return f"./{self.raw}" if not self.uplvl else "../" * self.uplvl + self.raw
        elif self.anchor_mode is PathGlobAnchorMode.DECLARED_PATH:
            return self.raw
        else:
            return f"{self.anchor_mode.value}{self.raw}"

    @memoized_classmethod
    def create(  # type: ignore[misc]
        cls: type[PathGlob], raw: str, anchor_mode: PathGlobAnchorMode, glob: str, uplvl: int
    ) -> PathGlob:
        return cls(raw=raw, anchor_mode=anchor_mode, glob=re.compile(glob), uplvl=uplvl)

    @classmethod
    def parse(cls, pattern: str, base: str) -> PathGlob:
        org_pattern = pattern
        if not isinstance(pattern, str):
            raise ValueError(f"invalid path glob, expected string but got: {pattern!r}")
        anchor_mode = PathGlobAnchorMode.parse(pattern)
        if anchor_mode is PathGlobAnchorMode.DECLARED_PATH:
            pattern = os.path.join(base, pattern.lstrip("/"))

        if anchor_mode is PathGlobAnchorMode.FLOATING:
            snap_to_path = not pattern.startswith(".")
        else:
            snap_to_path = False

        pattern = os.path.normpath(pattern)
        uplvl = pattern.count("../")
        if anchor_mode is not PathGlobAnchorMode.FLOATING:
            pattern = pattern.lstrip("./")

        if uplvl > 0 and anchor_mode is not PathGlobAnchorMode.INVOKED_PATH:
            raise ValueError(
                f"Internal Error: unexpected `uplvl` {uplvl} for pattern={org_pattern!r}, "
                f"{anchor_mode}, base={base!r}. Please file a bug report!"
            )

        return cls.create(  # type: ignore[call-arg]
            raw=pattern,
            anchor_mode=anchor_mode,
            glob=cls._translate_pattern_to_regexp(pattern, snap_to_path=snap_to_path),
            uplvl=uplvl,
        )

    @staticmethod
    def _translate_pattern_to_regexp(pattern: str, snap_to_path: bool) -> str:
        # Escape regexp characters, then restore any `*`s.
        glob = re.escape(pattern).replace(r"\*", "*")
        # Translate recursive `**` globs to regexp, any adjacent `/` is optional.
        glob = glob.replace("/**", r"(/.<<$>>)?")
        glob = glob.replace("**/", r"/?\b")
        glob = glob.replace("**", r".<<$>>")
        # Translate `*` to match any path segment.
        glob = glob.replace("*", r"[^/]<<$>>")
        # Restore `*`s that was "escaped" during translation.
        glob = glob.replace("<<$>>", r"*")
        # Snap to closest `/`
        if snap_to_path and glob and glob[0].isalnum():
            glob = r"/?\b" + glob

        return glob + r"$"

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


RULE_REGEXP = "|".join(
    (
        r"(?:<(?P<type>[^>]*)>)",
        r"(?:\[(?P<path>[^]]*)\])",
        r"(?:\((?P<tags>[^)]*)\))",
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
        type_ = f"<{self.type_}>" if self.type_ else ""
        tags = (
            f"({', '.join(str(tag) if ',' not in tag else repr(tag) for tag in self.tags)})"
            if self.tags
            else ""
        )
        path = self.path or ""
        if path and (type_ or tags):
            path = f"[{path}]"
        return f"{type_}{path}{tags}" or "!*"

    @memoized_classmethod
    def create(  # type: ignore[misc]
        cls: type[TargetGlob],
        type_: str | None,
        path: PathGlob | None,
        tags: tuple[str, ...] | None,
    ) -> TargetGlob:
        return cls(type_=type_, path=path, tags=tags)

    @classmethod
    def parse(cls, spec: str | Mapping[str, Any], base: str) -> TargetGlob:
        if isinstance(spec, str):
            spec_dict = cls._parse_string(spec)
        elif isinstance(spec, Mapping):
            spec_dict = spec
        else:
            raise ValueError(f"Invalid target spec, expected string or dict but got: {spec!r}")

        if not spec_dict:
            raise ValueError("Target spec must not be empty.")

        return cls.create(  # type: ignore[call-arg]
            type_=spec_dict.get("type"),
            path=(PathGlob.parse(spec_dict["path"], base) if spec_dict.get("path") else None),
            tags=cls._parse_tags(spec_dict.get("tags")),
        )

    @staticmethod
    def _parse_string(spec: str) -> Mapping[str, Any]:
        if not spec:
            return {}
        if spec[0] not in "<[(":
            return dict(path=spec)
        return {
            tag: val
            for tag, val in itertools.chain.from_iterable(
                m.groupdict().items() for m in re.finditer(RULE_REGEXP, spec)
            )
            if val is not None
        }

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

    @staticmethod
    def address_path(address: Address) -> str:
        if address.is_file_target:
            return address.filename
        elif address.is_generated_target:
            return address.spec.replace(":", "/").lstrip("/")
        else:
            return address.spec_path

    def match(self, address: Address, adaptor: TargetAdaptor, base: str) -> bool:
        if not (self.type_ or self.path or self.tags):
            # Nothing rules this target in.
            return False

        # target type
        if self.type_ and not fnmatchcase(adaptor.type_alias, self.type_):
            return False
        # target path (includes filename for source targets)
        if self.path and not self.path.match(self.address_path(address), base):
            return False
        # target tags
        if self.tags:
            # Use adaptor.kwargs with caution, unvalidated input data from BUILD file.
            target_tags = adaptor.kwargs.get("tags")
            if not isinstance(target_tags, Sequence) or isinstance(target_tags, str):
                # Bad tags value
                return False
            if not all(
                any(fnmatchcase(str(tag), pattern) for tag in target_tags) for pattern in self.tags
            ):
                return False

        # Nothing rules this target out.
        return True
