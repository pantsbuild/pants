# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class NativeParsedPythonDependencies:
    imports: FrozenDict[str, tuple[int, bool]]
    string_candidates: FrozenDict[str, int]

    def __init__(self, imports: dict[str, tuple[int, bool]], string_candidates: dict[str, int]):
        object.__setattr__(self, "imports", FrozenDict(imports))
        object.__setattr__(self, "string_candidates", FrozenDict(string_candidates))


@dataclass(frozen=True)
class ParsedJavascriptDependencyCandidate:
    file_imports: frozenset[str]
    package_imports: frozenset[str]


@dataclass(frozen=True)
class NativeParsedJavascriptDependencies:
    imports: dict[str, ParsedJavascriptDependencyCandidate]

    def __init__(self, imports: dict[str, ParsedJavascriptDependencyCandidate]):
        object.__setattr__(self, "imports", imports)

    @property
    def file_imports(self) -> frozenset[str]:
        return frozenset(
            string for candidate in self.imports.values() for string in candidate.file_imports
        )

    @property
    def package_imports(self) -> frozenset[str]:
        return frozenset(
            string for candidate in self.imports.values() for string in candidate.package_imports
        )


@dataclass(frozen=True)
class NativeParsedDockerfileInfo:
    source: str
    build_args: tuple[str, ...]  # "ARG_NAME=VALUE", ...
    copy_source_paths: tuple[str, ...]
    copy_build_args: tuple[str, ...]  # "ARG_NAME=UPSTREAM_TARGET_ADDRESS", ...
    from_image_build_args: tuple[str, ...]  # "ARG_NAME=UPSTREAM_TARGET_ADDRESS", ...
    version_tags: tuple[str, ...]  # "STAGE TAG", ...
