# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go import target_type_rules
from pants.backend.go.go_sources import load_go_binary
from pants.backend.go.goals import check, package_binary, run_binary, tailor, test
from pants.backend.go.lint.gofmt import skip_field as gofmt_skip_field
from pants.backend.go.lint.gofmt.rules import rules as gofmt_rules
from pants.backend.go.subsystems import golang
from pants.backend.go.target_types import (
    GoBinaryTarget,
    GoModTarget,
    GoPackageTarget,
    GoThirdPartyPackageTarget,
)
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    pkg_analyzer,
    sdk,
    tests_analysis,
    third_party_pkg,
)


def target_types():
    return [GoPackageTarget, GoModTarget, GoThirdPartyPackageTarget, GoBinaryTarget]


def rules():
    return [
        *assembly.rules(),
        *build_pkg.rules(),
        *build_pkg_target.rules(),
        *check.rules(),
        *third_party_pkg.rules(),
        *golang.rules(),
        *import_analysis.rules(),
        *go_mod.rules(),
        *first_party_pkg.rules(),
        *link.rules(),
        *pkg_analyzer.rules(),
        *sdk.rules(),
        *tests_analysis.rules(),
        *tailor.rules(),
        *target_type_rules.rules(),
        *test.rules(),
        *run_binary.rules(),
        *package_binary.rules(),
        *load_go_binary.rules(),
        # Gofmt
        *gofmt_rules(),
        *gofmt_skip_field.rules(),
    ]
