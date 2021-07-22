# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.go.tailor import PutativeGoModuleTargetsRequest, PutativeGoPackageTargetsRequest
from pants.backend.go.tailor import rules as go_tailor_rules
from pants.backend.go.target_types import GoModule, GoPackage
from pants.core.goals.tailor import (
    AllOwnedSources,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsSearchPaths,
)
from pants.core.goals.tailor import rules as core_tailor_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


def test_find_putative_go_package_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *core_tailor_rules(),
            *go_tailor_rules(),
            QueryRule(PutativeTargets, [PutativeGoPackageTargetsRequest, AllOwnedSources]),
            QueryRule(AllOwnedSources, ()),
        ],
        target_types=[
            GoPackage,
        ],
    )
    rule_runner.set_options(["--backend-packages=pants.backend.experimental.go"])

    rule_runner.write_files(
        {
            "src/go/owned/BUILD": "go_package()\n",
            "src/go/owned/src.go": "package owned\n",
            "src/go/unowned/src.go": "package unowned\n",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoPackageTargetsRequest(PutativeTargetsSearchPaths(("src/",))),
            AllOwnedSources(
                [
                    "src/go/owned/src.go",
                ]
            ),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoPackage,
                "src/go/unowned",
                "unowned",
                [
                    "src.go",
                ],
            ),
        ]
    )


def test_find_putative_go_module_targets() -> None:
    rule_runner = RuleRunner(
        rules=[
            *core_tailor_rules(),
            *go_tailor_rules(),
            QueryRule(PutativeTargets, [PutativeGoModuleTargetsRequest, AllOwnedSources]),
            QueryRule(AllOwnedSources, ()),
        ],
        target_types=[
            GoModule,
        ],
    )
    rule_runner.set_options(["--backend-packages=pants.backend.experimental.go"])

    rule_runner.write_files(
        {
            "src/go/owned/BUILD": "go_module()\n",
            "src/go/owned/go.mod": "module example.com/src/go/owned\n",
            "src/go/unowned/go.mod": "module example.com/src/go/unowned\n",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoModuleTargetsRequest(PutativeTargetsSearchPaths(("src/",))),
            AllOwnedSources(
                [
                    "src/go/owned/go.mod",
                ]
            ),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoModule,
                "src/go/unowned",
                "unowned",
                [
                    "go.mod",
                ],
            ),
        ]
    )
