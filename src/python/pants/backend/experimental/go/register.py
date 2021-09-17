# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go import target_type_rules
from pants.backend.go import target_types as go_target_types
from pants.backend.go.goals import custom_goals, package_binary, tailor
from pants.backend.go.subsystems import golang
from pants.backend.go.target_types import GoBinary, GoExternalPackageTarget, GoModule, GoPackage
from pants.backend.go.util_rules import build_go_pkg, go_mod, go_pkg, import_analysis, sdk


def target_types():
    return [GoBinary, GoPackage, GoModule, GoExternalPackageTarget]


def rules():
    return [
        *build_go_pkg.rules(),
        *golang.rules(),
        *go_target_types.rules(),
        *import_analysis.rules(),
        *go_mod.rules(),
        *go_pkg.rules(),
        *sdk.rules(),
        *tailor.rules(),
        *target_type_rules.rules(),
        *custom_goals.rules(),
        *package_binary.rules(),
    ]
