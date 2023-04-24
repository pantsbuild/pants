# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.collection import DeduplicatedCollection
from pants.util.frozendict import FrozenDict

@dataclass(frozen=True)
class ParsedPythonImportInfo:
    lineno: int
    # An import is considered "weak" if we're unsure if a dependency will exist between the parsed
    # file and the parsed import.
    # Examples of "weak" imports include string imports (if enabled) or those inside a try block
    # which has a handler catching ImportError.
    weak: bool


class ParsedPythonImports(FrozenDict[str, ParsedPythonImportInfo]):
    """All the discovered imports from a Python source file mapped to the relevant info."""


class ParsedPythonAssetPaths(DeduplicatedCollection[str]):
    """All the discovered possible assets from a Python source file."""

    # N.B. Don't set `sort_input`, as the input is already sorted


@dataclass(frozen=True)
class ParsedPythonDependencies:
    imports: ParsedPythonImports
    assets: ParsedPythonAssetPaths

    @staticmethod
    def create(
        imports: dict[str, tuple[str, bool]],
        assets: tuple[str, ...],
    )-> 'ParsedPythonDependencies':
        return ParsedPythonDependencies(
            ParsedPythonImports({
                key: ParsedPythonImportInfo(*value) for key, value in imports.items()
            }),
            ParsedPythonAssetPaths(assets),
        )
