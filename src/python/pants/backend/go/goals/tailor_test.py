# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.tailor import PutativeGoTargetsRequest, has_package_main
from pants.backend.go.goals.tailor import rules as go_tailor_rules
from pants.backend.go.target_types import GoBinaryTarget, GoModTarget
from pants.backend.go.util_rules import first_party_pkg, go_mod, sdk, third_party_pkg
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
            QueryRule(PutativeTargets, [PutativeGoTargetsRequest, AllOwnedSources]),
        ],
        target_types=[GoModTarget, GoBinaryTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_find_putative_go_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            # No `go_mod`, should be created.
            "src/go/unowned/go.mod": "module example.com/src/go/unowned\n",
            # Already has `go_mod`.
            "src/go/owned/go.mod": "module example.com/src/go/owned\n",
            "src/go/owned/BUILD": "go_mod()\n",
            # Missing `go_binary()`, should be created.
            "src/go/owned/pkg1/app.go": "package main",
            # Already has a `go_binary()`.
            "src/go/owned/pkg2/app.go": "package main",
            "src/go/owned/pkg2/BUILD": "go_binary()",
            # Has a `go_binary` defined in a different directory.
            "src/go/owned/pkg3/subdir/app.go": "package main",
            "src/go/owned/pkg3/BUILD": "go_binary(main='src/go/owned/pkg3/subdir/:../../owned')",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoTargetsRequest(PutativeTargetsSearchPaths(("src/",))),
            AllOwnedSources(["src/go/owned/go.mod"]),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoModTarget, path="src/go/unowned", name="unowned", triggering_sources=["go.mod"]
            ),
            PutativeTarget.for_target_type(
                GoBinaryTarget,
                path="src/go/owned/pkg1",
                name="bin",
                triggering_sources=[],
                kwargs={"name": "bin"},
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
