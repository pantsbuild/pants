# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import GoExternalPackageTarget, GoModTarget, GoPackage
from pants.backend.go.util_rules import (
    assembly,
    build_go_pkg,
    compile,
    external_module,
    go_mod,
    go_pkg,
    import_analysis,
    sdk,
)
from pants.backend.go.util_rules.build_go_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *source_files.rules(),
            *sdk.rules(),
            *assembly.rules(),
            *build_go_pkg.rules(),
            *compile.rules(),
            *import_analysis.rules(),
            *go_mod.rules(),
            *go_pkg.rules(),
            *external_module.rules(),
            *target_type_rules.rules(),
            QueryRule(BuiltGoPackage, [BuildGoPackageRequest]),
        ],
        target_types=[GoPackage, GoModTarget, GoExternalPackageTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_build_package_with_assembly(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/assembly
                go 1.17
                """
            ),
            "main.go": dedent(
                """\
                package main

                import "fmt"

                func main() {
                    fmt.Println(add(1, 2))
                }
                """
            ),
            "add_amd64.go": "package main\nfunc add(x, y int64) int64",
            "add_arm64.go": "package main\nfunc add(x, y int64) int64",
            # Based on https://davidwong.fr/goasm/add.
            "add_amd64.s": dedent(
                """\
                TEXT ·add(SB),$0-24
                    MOVQ  x+0(FP), BX
                    MOVQ  y+8(FP), BP

                    ADDQ  BP, BX
                    MOVQ  BX, ret+16(FP)
                    RET
                """
            ),
            # Based on combining https://davidwong.fr/goasm/add and `go tool compile -S` to get
            # ARM instructions.
            "add_arm64.s": dedent(
                """\
                TEXT ·add(SB),$0-24
                    MOVD  x+0(FP), R0
                    MOVD  y+8(FP), R1

                    ADD   R1, R0, R0
                    MOVD  R0, ret+16(FP)
                    RET
                """
            ),
            "BUILD": dedent(
                """\
                go_module(name="mod")
                go_package(name="main")
                """
            ),
        }
    )

    built_package = rule_runner.request(
        BuiltGoPackage,
        [BuildGoPackageRequest(Address("", target_name="main"))],
    )
    assert built_package.import_path == "example.com/assembly/"
