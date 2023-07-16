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
class NativeParsedJavascriptDependencies:
    file_imports: frozenset[str]
    package_imports: frozenset[str]

    def __init__(self, file_imports: set[str], package_imports: set[str]):
        object.__setattr__(self, "file_imports", file_imports)
        object.__setattr__(self, "package_imports", package_imports)
