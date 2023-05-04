# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.util.frozendict import FrozenDict


@dataclass(frozen=True)
class NativeParsedPythonDependencies:
    imports: FrozenDict[str, tuple[int, bool]]
    string_candidates: FrozenDict[str, int]

    @staticmethod
    def create_from_native(
        imports: dict[str, tuple[int, bool]],
        string_candidates: dict[str, int],
    ) -> "NativeParsedPythonDependencies":
        return NativeParsedPythonDependencies(
            FrozenDict(imports),
            FrozenDict(string_candidates),
        )
