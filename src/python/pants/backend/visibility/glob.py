# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import os.path
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Pattern

from pants.engine.addresses import Address
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.util.memo import memoized_classmethod
from pants.util.strutil import softwrap


def is_path_glob(spec: str) -> bool:
    """Check if `spec` should be treated as a `path` glob."""
    return len(spec) > 0 and (spec[0].isalnum() or spec[0] in "_.:/*")


def glob_to_regexp(pattern: str, snap_to_path: bool = False) -> str:
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


@dataclass(frozen=True)
class Glob:
    raw: str
    regexp: Pattern = field(compare=False)

    @classmethod
    def create(cls, pattern: str) -> Glob:
        return cls(pattern, re.compile(glob_to_regexp(pattern)))

    def match(self, value: str) -> bool:
        return bool(re.match(self.regexp, value))

    def __str__(self) -> str:
        return self.raw


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
    anchor_mode: PathGlobAnchorMode
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
            glob=glob_to_regexp(pattern, snap_to_path=snap_to_path),
            uplvl=uplvl,
        )

    def _match_path(self, path: str, base: str) -> str | None:
        if self.anchor_mode is PathGlobAnchorMode.INVOKED_PATH:
            path = os.path.relpath(path or ".", base + "/.." * self.uplvl)
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
        r"(?:\[(?P<path>[^]:]*)?(?::(?P<name>[^]]*))?\])",
        r"(?:\((?P<tags>[^)]*)\))",
    )
)


@dataclass(frozen=True)
class TargetGlob:
    type_: Glob | None
    name: Glob | None
    path: PathGlob | None
    tags: tuple[Glob, ...] | None

    def __post_init__(self) -> None:
        for what, value in (("type", self.type_), ("name", self.name)):
            if not isinstance(value, (Glob, type(None))):
                raise ValueError(f"invalid target {what}, expected glob but got: {value!r}")
        if not isinstance(self.path, (PathGlob, type(None))):
            raise ValueError(f"invalid target path, expected glob but got: {self.path!r}")
        if not isinstance(self.tags, (tuple, type(None))):
            raise ValueError(
                f"invalid target tags, expected sequence of values but got: {self.tags!r}"
            )

    def __str__(self) -> str:
        """Full syntax:

            <target-type>[path:target-name](tag-1, tag-2)

        If no target-type nor tags:

            path:target-name
        """
        type_ = f"<{self.type_}>" if self.type_ else ""
        name = f":{self.name}" if self.name else ""
        tags = (
            f"({', '.join(str(tag) if ',' not in tag.raw else repr(tag.raw) for tag in self.tags)})"
            if self.tags
            else ""
        )
        path = f"{self.path}{name}" if self.path else name
        if path and (type_ or tags):
            path = f"[{path}]"
        return f"{type_}{path}{tags}" or "!*"

    @memoized_classmethod
    def create(  # type: ignore[misc]
        cls: type[TargetGlob],
        type_: str | None,
        name: str | None,
        path: str | None,
        base: str,
        tags: tuple[str, ...] | None,
    ) -> TargetGlob:
        return cls(
            type_=Glob.create(type_) if type_ else None,
            path=PathGlob.parse(path, base) if path else None,
            name=Glob.create(name) if name else None,
            tags=tuple(Glob.create(tag) for tag in tags) if tags else None,
        )

    @classmethod
    def parse(cls: type[TargetGlob], spec: str | Mapping[str, Any], base: str) -> TargetGlob:
        if isinstance(spec, str):
            spec_dict = cls._parse_string(spec)
        elif isinstance(spec, Mapping):
            spec_dict = spec
        else:
            raise ValueError(f"Invalid target spec, expected string or dict but got: {spec!r}")

        if not spec_dict:
            raise ValueError(f"Target spec must not be empty. {spec!r}")

        return cls.create(  # type: ignore[call-arg]
            type_=str(spec_dict["type"]) if "type" in spec_dict else None,
            name=str(spec_dict["name"]) if "name" in spec_dict else None,
            path=str(spec_dict["path"]) if "path" in spec_dict else None,
            base=base,
            tags=cls._parse_tags(spec_dict.get("tags")),
        )

    @staticmethod
    def _parse_string(spec: str) -> Mapping[str, Any]:
        if not spec:
            return {}
        if is_path_glob(spec):
            path, _, name = spec.partition(":")
            return dict(path=path, name=name)
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
        if not (self.type_ or self.name or self.path or self.tags):
            # Nothing rules this target in.
            return False

        # target type
        if self.type_ and not self.type_.match(adaptor.type_alias):
            return False
        # target name
        if self.name and not self.name.match(address.target_name):
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
            if not all(any(glob.match(str(tag)) for tag in target_tags) for glob in self.tags):
                return False

        # Nothing rules this target out.
        return True
