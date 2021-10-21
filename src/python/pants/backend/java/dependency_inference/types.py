# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class JavaImport:
    name: str
    is_static: bool = False
    is_asterisk: bool = False

    @classmethod
    def from_json_dict(cls, imp: dict[str, Any]) -> JavaImport:
        return cls(
            name=imp["name"],
            is_asterisk=imp["isAsterisk"],
            is_static=imp["isStatic"],
        )


@dataclass(frozen=True)
class JavaSourceDependencyAnalysis:
    declared_package: str
    imports: Sequence[JavaImport]
    top_level_types: Sequence[str]
    consumed_unqualified_types: Sequence[str]

    @classmethod
    def from_json_dict(cls, analysis: dict[str, Any]) -> JavaSourceDependencyAnalysis:
        return cls(
            declared_package=analysis["declaredPackage"],
            imports=[JavaImport.from_json_dict(imp) for imp in analysis["imports"]],
            top_level_types=analysis["topLevelTypes"],
            consumed_unqualified_types=analysis["consumedUnqualifiedTypes"],
        )
