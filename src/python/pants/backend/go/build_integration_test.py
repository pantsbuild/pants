# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import build, import_analysis, module, pkg, sdk, target_type_rules
from pants.backend.go.build import GoBinaryFieldSet
from pants.backend.go.target_types import GoBinary, GoModule, GoPackage
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.util_rules import external_tool, source_files
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[GoBinary, GoPackage, GoModule],
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *import_analysis.rules(),
            *build.rules(),
            *pkg.rules(),
            *module.rules(),
            *target_type_rules.rules(),
            *sdk.rules(),
            QueryRule(BuiltPackage, (GoBinaryFieldSet,)),
        ],
    )


def build_package(rule_runner: RuleRunner, binary_target: Target) -> BuiltPackage:
    field_set = GoBinaryFieldSet.create(binary_target)
    return rule_runner.request(BuiltPackage, [field_set])


def test_package_simple(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": "module foo.example.com\n",
            "BUILD": "go_module(name='root')\n",
            "project/main.go": dedent(
                """\
                package main

                import (
                \t"fmt"
                )

                func main() {
                \tfmt.Println("Hello world!")
                }
                """
            ),
            "project/BUILD": dedent(
                """\
                go_package(name='main', import_path='main')
                go_binary(name='bin', binary_name='foo', main=':main')
                """
            ),
        }
    )
    binary_tgt = rule_runner.get_target(Address("project", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "project/foo"


def test_package_with_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": "module foo.example.com\n",
            "BUILD": "go_module(name='root')\n",
            "project/lib/lib.go": dedent(
                """\
                package lib

                import (
                \t"fmt"
                )

                func Quote(s string) string {
                \treturn fmt.Sprintf(">> %s <<", s)
                }
                """
            ),
            "project/lib/BUILD": "go_package(import_path='example.com/lib')",
            "project/main.go": dedent(
                """\
                package main

                import (
                \t"fmt"
                \t"example.com/lib"
                )

                func main() {
                \tfmt.Println(lib.Quote("Hello world!"))
                }
                """
            ),
            "project/BUILD": dedent(
                """\
                go_package(name='main', import_path='main', dependencies=['project/lib'])
                go_binary(name='bin', binary_name='foo', main=':main')
                """
            ),
        }
    )
    binary_tgt = rule_runner.get_target(Address("project", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "project/foo"
