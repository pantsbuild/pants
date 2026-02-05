# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Sequence

from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class NativePythonFileDependencies:
    imports: FrozenDict[str, tuple[int, bool]]
    string_candidates: FrozenDict[str, int]

    def __init__(self, imports: dict[str, tuple[int, bool]], string_candidates: dict[str, int]):
        object.__setattr__(self, "imports", FrozenDict(imports))
        object.__setattr__(self, "string_candidates", FrozenDict(string_candidates))


@dataclass(frozen=True)
class NativePythonFilesDependencies:
    path_to_deps: FrozenDict[str, NativePythonFileDependencies]


@dataclass(frozen=True)
class JavascriptDependencyCandidate:
    file_imports: frozenset[str]
    package_imports: frozenset[str]

    def __init__(self, file_imports: AbstractSet[str], package_imports: AbstractSet[str]):
        object.__setattr__(self, "file_imports", frozenset(file_imports))
        object.__setattr__(self, "package_imports", frozenset(package_imports))


@dataclass(frozen=True)
class NativeJavascriptFileDependencies:
    imports: FrozenDict[str, JavascriptDependencyCandidate]

    def __init__(self, imports: dict[str, JavascriptDependencyCandidate]):
        object.__setattr__(self, "imports", FrozenDict(imports))

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
class NativeJavascriptFilesDependencies:
    path_to_deps: FrozenDict[str, NativeJavascriptFileDependencies]


@dataclass(frozen=True)
class NativeDockerfileInfo:
    source: str
    build_args: tuple[str, ...]  # "ARG_NAME=VALUE", ...
    copy_source_paths: tuple[str, ...]
    copy_build_args: tuple[str, ...]  # "ARG_NAME=UPSTREAM_TARGET_ADDRESS", ...
    from_image_build_args: tuple[str, ...]  # "ARG_NAME=UPSTREAM_TARGET_ADDRESS", ...
    version_tags: tuple[str, ...]  # "STAGE TAG", ...

    def __init__(
        self,
        source: str,
        build_args: Sequence[str],
        copy_source_paths: Sequence[str],
        copy_build_args: Sequence[str],
        from_image_build_args: Sequence[str],
        version_tags: Sequence[str],
    ):
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "build_args", tuple(build_args))
        object.__setattr__(self, "copy_source_paths", tuple(copy_source_paths))
        object.__setattr__(self, "copy_build_args", tuple(copy_build_args))
        object.__setattr__(self, "from_image_build_args", tuple(from_image_build_args))
        object.__setattr__(self, "version_tags", tuple(version_tags))


@dataclass(frozen=True)
class NativeDockerfileInfos:
    path_to_infos: FrozenDict[str, NativeDockerfileInfo]
