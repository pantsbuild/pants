# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
import subprocess
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals import package_binary
from pants.backend.go.goals.package_binary import GoBinaryFieldSet
from pants.backend.go.target_types import (
    GoBinaryTarget,
    GoModTarget,
    GoPackageTarget,
    GoVendoredPackageTarget,
)
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    implicit_linker_deps,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
    vendor,
)
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *implicit_linker_deps.rules(),
            *import_analysis.rules(),
            *link.rules(),
            *package_binary.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *third_party_pkg.rules(),
            *vendor.rules(),
            QueryRule(BuiltPackage, (GoBinaryFieldSet,)),
        ],
        target_types=[
            GoBinaryTarget,
            GoModTarget,
            GoPackageTarget,
            GoVendoredPackageTarget,
        ],
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def build_package(rule_runner: RuleRunner, binary_target: Target) -> BuiltPackage:
    field_set = GoBinaryFieldSet.create(binary_target)
    result = rule_runner.request(BuiltPackage, [field_set])
    rule_runner.write_digest(result.digest)
    return result


def test_basic_vendored_package(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": dedent(
                """\
            go_mod(name="mod")
            go_package()
            go_binary(name="bin")
            """
            ),
            "foo/go.mod": dedent(
                """\
            module example.pantsbuild.org/main
            require lib.pantsbuild.org/concat v0.0.1
            """
            ),
            "foo/main.go": dedent(
                """\
            package main
            import (
              "fmt"
              "os"
              "lib.pantsbuild.org/concat"
            )
            func main() {
              x := os.Args[1]
              y := os.Args[2]
              fmt.Printf("%s\n", concat.Join(x, y))
            }
            """
            ),
            "foo/vendor/module.txt": dedent(
                """\
            # lib.pantsbuild.org/concat v0.0.1
            ## explicit; go 1.17
            lib.pantsbuild.org/concat
            """
            ),
            "foo/vendor/lib.pantsbuild.org/concat/concat.go": dedent(
                """\
            package concat
            func Join(x, y string) string {
              return x + y
            }
            """
            ),
        }
    )

    binary_tgt = rule_runner.get_target(Address("foo", target_name="bin"))
    built_package = build_package(rule_runner, binary_tgt)
    assert len(built_package.artifacts) == 1
    assert built_package.artifacts[0].relpath == "bin"

    result = subprocess.run(
        [os.path.join(rule_runner.build_root, "bin"), "Hello ", " world!"], stdout=subprocess.PIPE
    )
    assert result.returncode == 0
    assert result.stdout == b"Hello world!\n"
