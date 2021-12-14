# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init


@dataclass(unsafe_hash=True)
@frozen_after_init
class EmbedConfig:
    patterns: FrozenDict[str, tuple[str, ...]]
    files: FrozenDict[str, str]

    def __init__(self, patterns: Mapping[str, Iterable[str]], files: Mapping[str, str]) -> None:
        """Configuration passed to the Go compiler to configure file embedding.

        The compiler relies entirely on the caller to map embed patterns to actual filesystem
        paths. All embed patterns
        contained in the package must be mapped. Consult
        `FirstPartyPkgAnalysis.embed_patterns` for the embed patterns obtained from analysis.

        :param patterns: Maps each pattern provided via a //go:embed directive to a list of file
          paths relative to the package directory for files to embed for that pattern. When the
          embedded variable is an `embed.FS`, those relative file paths define the virtual
          directory hierarchy exposed by the embed.FS filesystem abstraction. The relative file
          paths are resolved to actual filesystem paths for their content by consulting the
          `files` dictionary.
        :param files: Maps each virtual, relative file path used as a value in the `patterns`
          dictionary to the actual filesystem path with that file's content.
        """
        self.patterns = FrozenDict({k: tuple(v) for k, v in patterns.items()})
        self.files = FrozenDict(files)

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> EmbedConfig | None:
        result = cls(
            patterns=FrozenDict(
                {key: tuple(value) for key, value in d.get("Patterns", {}).items()}
            ),
            files=FrozenDict(d.get("Files", {})),
        )
        return result if result else None

    def to_embedcfg(self) -> bytes:
        data = {
            "Patterns": dict(self.patterns),
            "Files": dict(self.files),
        }
        return json.dumps(data).encode("utf-8")

    def __bool__(self) -> bool:
        return bool(self.patterns) or bool(self.files)

    def merge(self, other: EmbedConfig) -> EmbedConfig:
        """Merge two EmbedConfig's into one.

        Overlapping keys must have the same values.
        """
        overlapping_patterns_keys = set(self.patterns.keys()) & set(other.patterns.keys())
        for key in overlapping_patterns_keys:
            if self.patterns[key] != other.patterns[key]:
                raise AssertionError(
                    "Unable to merge conflicting golang file embed configurations. This should not have occurred. "
                    "Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose "
                    "with the following information: "
                    f"Patterns Key: {key}; Left: {self.patterns[key]}; Right: {other.patterns[key]} "
                )

        overlapping_files_keys = set(self.files.keys()) & set(other.files.keys())
        for key in overlapping_files_keys:
            if self.files[key] != other.files[key]:
                raise AssertionError(
                    "Unable to merge conflicting golang file embed configurations. This should not have occurred. "
                    "Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose "
                    "with the following information: "
                    f"Files Key: {key}; Left: {self.patterns[key]}; Right: {other.patterns[key]} "
                )

        return EmbedConfig(
            patterns={**self.patterns, **other.patterns},
            files={**self.files, **other.files},
        )
