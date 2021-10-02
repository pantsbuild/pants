# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
import subprocess
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals import package_binary
from pants.backend.go.goals.package_binary import GoBinaryFieldSet
from pants.backend.go.target_types import GoBinary, GoModTarget, GoPackage
from pants.backend.go.util_rules import (
    assembly,
    build_go_pkg,
    compile,
    external_module,
    go_mod,
    go_pkg,
    import_analysis,
    link,
    sdk,
)
from pants.core.goals.package import BuiltPackage
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture()
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *assembly.rules(),
            *compile.rules(),
            *source_files.rules(),
            *import_analysis.rules(),
            *package_binary.rules(),
            *build_go_pkg.rules(),
            *go_pkg.rules(),
            *go_mod.rules(),
            *link.rules(),
            *target_type_rules.rules(),
            *external_module.rules(),
            *sdk.rules(),
            QueryRule(BuiltPackage, (GoBinaryFieldSet,)),
        ],
        target_types=[GoBinary, GoPackage, GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def build_package(rule_runner: RuleRunner, binary_target: Target) -> BuiltPackage:
    field_set = GoBinaryFieldSet.create(binary_target)
    result = rule_runner.request(BuiltPackage, [field_set])
    rule_runner.write_digest(result.digest)
    return result


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
                go_mod(name='mod')
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

    result = subprocess.run([os.path.join(rule_runner.build_root, "bin")], stdout=subprocess.PIPE)
    assert result.returncode == 0
    assert result.stdout == b"Hello world!\n"


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
                go_mod(name='mod')
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

    result = subprocess.run([os.path.join(rule_runner.build_root, "bin")], stdout=subprocess.PIPE)
    assert result.returncode == 0
    assert result.stdout == b">> Hello world! <<\n"
