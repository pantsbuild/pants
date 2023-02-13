# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.go import target_type_rules
from pants.backend.go.go_sources import load_go_binary
from pants.backend.go.goals import check, generate, package_binary, run_binary, tailor, test
from pants.backend.go.lint.gofmt import skip_field as gofmt_skip_field
from pants.backend.go.lint.gofmt.rules import rules as gofmt_rules
from pants.backend.go.target_types import (
    GoBinaryTarget,
    GoModTarget,
    GoPackageSourcesField,
    GoPackageTarget,
    GoThirdPartyPackageTarget,
)
from pants.backend.go.util_rules import (
    assembly,
    binary,
    build_opts,
    build_pkg,
    build_pkg_target,
    cgo,
    coverage,
    coverage_output,
    first_party_pkg,
    go_bootstrap,
    go_mod,
    goroot,
    implicit_linker_deps,
    import_analysis,
    import_config,
    link,
    pkg_analyzer,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.core.util_rules.wrap_source import wrap_source_rule_and_target

wrap_golang = wrap_source_rule_and_target(GoPackageSourcesField, "go_package_sources")


def target_types():
    return [
        GoPackageTarget,
        GoModTarget,
        GoThirdPartyPackageTarget,
        GoBinaryTarget,
        *wrap_golang.target_types,
    ]


def rules():
    return [
        *assembly.rules(),
        *binary.rules(),
        *build_opts.rules(),
        *build_pkg.rules(),
        *build_pkg_target.rules(),
        *check.rules(),
        *coverage.rules(),
        *coverage_output.rules(),
        *cgo.rules(),
        *third_party_pkg.rules(),
        *generate.rules(),
        *go_bootstrap.rules(),
        *goroot.rules(),
        *implicit_linker_deps.rules(),
        *import_analysis.rules(),
        *import_config.rules(),
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
        *wrap_golang.rules,
    ]
