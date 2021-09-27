# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go import target_type_rules
from pants.backend.go import target_types as go_target_types
from pants.backend.go.goals import custom_goals, package_binary, tailor
from pants.backend.go.subsystems import golang
from pants.backend.go.target_types import GoBinary, GoExternalPackageTarget, GoModule, GoPackage
from pants.backend.go.util_rules import (
    assembly,
    build_go_pkg,
    external_module,
    go_mod,
    go_pkg,
    import_analysis,
    link,
    sdk,
)


def target_types():
    return [GoBinary, GoPackage, GoModule, GoExternalPackageTarget]


def rules():
    return [
        *assembly.rules(),
        *build_go_pkg.rules(),
        *external_module.rules(),
        *golang.rules(),
        *go_target_types.rules(),
        *import_analysis.rules(),
        *go_mod.rules(),
        *go_pkg.rules(),
        *link.rules(),
        *sdk.rules(),
        *tailor.rules(),
        *target_type_rules.rules(),
        *custom_goals.rules(),
        *package_binary.rules(),
    ]
