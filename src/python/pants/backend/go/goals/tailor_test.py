# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.tailor import PutativeGoTargetsRequest, has_package_main
from pants.backend.go.goals.tailor import rules as go_tailor_rules
from pants.backend.go.target_types import GoBinaryTarget, GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    third_party_pkg,
)
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsSearchPaths,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *go_tailor_rules(),
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *assembly.rules(),
            *link.rules(),
            QueryRule(PutativeTargets, [PutativeGoTargetsRequest, AllOwnedSources]),
        ],
        target_types=[GoModTarget, GoBinaryTarget, GoPackageTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_find_go_mod_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"unowned/go.mod": "", "owned/go.mod": "", "owned/BUILD": "go_mod()"})
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources(["owned/go.mod"]),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoModTarget, path="unowned", name=None, triggering_sources=["go.mod"]
            )
        ]
    )


def test_find_go_package_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "unowned/f.go": "",
            "unowned/f1.go": "",
            "owned/f.go": "",
            "owned/BUILD": "go_package()",
            # Any `.go` files under a `testdata` or `vendor` folder should be ignored.
            "unowned/testdata/f.go": "",
            "unowned/testdata/subdir/f.go": "",
            "unowned/vendor/example.com/foo/bar.go": "",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources(["owned/f.go"]),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoPackageTarget,
                path="unowned",
                name=None,
                triggering_sources=["f.go", "f1.go"],
            )
        ]
    )


def test_find_go_binary_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "missing_binary_tgt/app.go": "package main",
            "missing_binary_tgt/BUILD": "go_package()",
            "tgt_already_exists/app.go": "package main",
            "tgt_already_exists/BUILD": "go_binary(name='bin')\ngo_package()",
            "missing_pkg_and_binary_tgt/app.go": "package main",
            "main_set_to_different_dir/subdir/app.go": "package main",
            "main_set_to_different_dir/subdir/BUILD": "go_package()",
            "main_set_to_different_dir/BUILD": "go_binary(main='main_set_to_different_dir/subdir')",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoTargetsRequest(PutativeTargetsSearchPaths(("",))),
            AllOwnedSources(
                [
                    "missing_binary_tgt/app.go",
                    "tgt_already_exists/app.go",
                    "main_set_to_different_dir/subdir/app.go",
                ]
            ),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoBinaryTarget,
                path="missing_binary_tgt",
                name="bin",
                triggering_sources=[],
            ),
            PutativeTarget.for_target_type(
                GoPackageTarget,
                path="missing_pkg_and_binary_tgt",
                name="missing_pkg_and_binary_tgt",
                triggering_sources=["app.go"],
                kwargs={},
            ),
            PutativeTarget.for_target_type(
                GoBinaryTarget,
                path="missing_pkg_and_binary_tgt",
                name="bin",
                triggering_sources=[],
            ),
        ]
    )


def test_has_package_main() -> None:
    assert has_package_main(b"package main")
    assert has_package_main(b"package main // comment 1233")
    assert has_package_main(b"\n\npackage main\n")
    assert not has_package_main(b"package foo")
    assert not has_package_main(b'var = "package main"')
    assert not has_package_main(b"   package main")
