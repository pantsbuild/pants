# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go import build, distribution, import_analysis, target_type_rules, target_types
from pants.backend.go.target_types import GoBinary, GoExternalModule, GoModule, GoPackage


def target_types():
    return [GoBinary, GoPackage, GoModule, GoExternalModule]


def rules():
    return [
        *build.rules(),
        *distribution.rules(),
        *import_analysis.rules(),
        *target_types.rules(),
        *target_type_rules.rules(),
    ]
