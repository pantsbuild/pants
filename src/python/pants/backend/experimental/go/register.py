# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go import (
    build,
    distribution,
    import_analysis,
    module,
    pkg,
    sdk,
    tailor,
    target_type_rules,
)
from pants.backend.go import target_types as go_target_types
from pants.backend.go.target_types import GoBinary, GoExternalModule, GoModule, GoPackage


def target_types():
    return [GoBinary, GoPackage, GoModule, GoExternalModule]


def rules():
    return [
        *build.rules(),
        *distribution.rules(),
        *go_target_types.rules(),
        *import_analysis.rules(),
        *module.rules(),
        *pkg.rules(),
        *sdk.rules(),
        *tailor.rules(),
        *target_type_rules.rules(),
    ]
