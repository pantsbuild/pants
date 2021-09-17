# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals import package_binary
from pants.backend.go.goals.package_binary import GoBinaryFieldSet
from pants.backend.go.target_types import GoBinary, GoModule, GoPackage
from pants.backend.go.util_rules import (
    build_go_pkg,
    external_module,
    go_mod,
    go_pkg,
    import_analysis,
    sdk,
)
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
            *package_binary.rules(),
            *build_go_pkg.rules(),
            *go_pkg.rules(),
            *go_mod.rules(),
            *target_type_rules.rules(),
            *external_module.rules(),
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
            "main.go": dedent(
                """\
                package main

                import (
                    "fmt"
                )

                func main() {
                    fmt.Println("Hello world!")
                }
                """
            ),
            "BUILD": dedent(
                """\
                go_module(name='go_mod')
                go_package(name='main')
                go_binary(name='bin', main=':main')
                """
            ),
        }
    )
    binary_tgt = rule_runner.get_target(Address("", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "bin"


def test_package_with_dependency(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "lib/lib.go": dedent(
                """\
                package lib

                import (
                    "fmt"
                )

                func Quote(s string) string {
                    return fmt.Sprintf(">> %s <<", s)
                }
                """
            ),
            "lib/BUILD": "go_package()",
            "main.go": dedent(
                """\
                package main

                import (
                    "fmt"
                    "foo.example.com/lib"
                )

                func main() {
                    fmt.Println(lib.Quote("Hello world!"))
                }
                """
            ),
            "go.mod": "module foo.example.com\n",
            "BUILD": dedent(
                """\
                go_module(name='go_mod')
                go_package(name='main')
                go_binary(name='bin', main=':main')
                """
            ),
        }
    )
    binary_tgt = rule_runner.get_target(Address("", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "bin"
