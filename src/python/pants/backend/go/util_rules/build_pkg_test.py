# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import GoModTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    compile,
    first_party_pkg,
    go_mod,
    import_analysis,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.build_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.engine.addresses import Address
from pants.engine.fs import Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.strutil import path_safe


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *compile.rules(),
            *import_analysis.rules(),
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *target_type_rules.rules(),
            QueryRule(BuiltGoPackage, [BuildGoPackageRequest]),
        ],
        target_types=[GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def assert_built(
    rule_runner: RuleRunner, addr: Address, *, expected_import_paths: list[str]
) -> None:
    built_package = rule_runner.request(BuiltGoPackage, [BuildGoPackageRequest(addr)])
    result_files = rule_runner.request(Snapshot, [built_package.digest]).files
    expected = {
        import_path: os.path.join("__pkgs__", path_safe(import_path), "__pkg__.a")
        for import_path in expected_import_paths
    }
    assert dict(built_package.import_paths_to_pkg_a_files) == expected
    assert sorted(result_files) == sorted(expected.values())


def test_build_internal_pkg(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/greeter
                go 1.17
                """
            ),
            "greeter.go": dedent(
                """\
                package greeter

                import "fmt"

                func Hello() {
                    fmt.Println("Hello world!")
                }
                """
            ),
            "BUILD": "go_mod(name='mod')",
        }
    )
    assert_built(
        rule_runner,
        Address("", target_name="mod", generated_name="./"),
        expected_import_paths=["example.com/greeter"],
    )


def test_build_external_pkg(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": dedent(
                """\
                module example.com/greeter
                go 1.17
                require github.com/google/uuid v1.3.0
                """
            ),
            "go.sum": dedent(
                """\
                github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                """
            ),
            "BUILD": "go_mod(name='mod')",
        }
    )
    import_path = "github.com/google/uuid"
    assert_built(
        rule_runner,
        Address("", target_name="mod", generated_name=import_path),
        expected_import_paths=[import_path],
    )


def test_build_dependencies(rule_runner: RuleRunner) -> None:
    """Check that we properly include (transitive) dependencies."""
    rule_runner.write_files(
        {
            "greeter/quoter/lib.go": dedent(
                """\
                package quoter

                import "fmt"

                func Quote(s string) string {
                    return fmt.Sprintf(">> %s <<", s)
                }
                """
            ),
            "greeter/lib.go": dedent(
                """\
                package greeter

                import (
                    "fmt"
                    "example.com/project/greeter/quoter"
                    "golang.org/x/xerrors"
                )

                func QuotedHello() {
                    xerrors.New("some error")
                    fmt.Println(quoter.Quote("Hello world!"))
                }
                """
            ),
            "main.go": dedent(
                """\
                package main

                import "example.com/project/greeter"

                func main() {
                    greeter.QuotedHello()
                }
                """
            ),
            "go.mod": dedent(
                """\
                module example.com/project
                go 1.17
                require golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543
                """
            ),
            "go.sum": dedent(
                """\
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543 h1:E7g+9GITq07hpfrRu66IVDexMakfv52eLZ2CXBWiKr4=
                golang.org/x/xerrors v0.0.0-20191204190536-9bdfabe68543/go.mod h1:I/5z698sn9Ka8TeJc9MKroUUfqBBauWjQqLJ2OPfmY0=
                """
            ),
            "BUILD": dedent(
                """\
                go_mod(name='mod')
                """
            ),
        }
    )

    xerrors_internal_import_path = "golang.org/x/xerrors/internal"
    assert_built(
        rule_runner,
        Address("", target_name="mod", generated_name=xerrors_internal_import_path),
        expected_import_paths=[xerrors_internal_import_path],
    )

    xerrors_import_paths = ["golang.org/x/xerrors", xerrors_internal_import_path]
    assert_built(
        rule_runner,
        Address("", target_name="mod", generated_name="golang.org/x/xerrors"),
        expected_import_paths=xerrors_import_paths,
    )

    quoter_import_path = "example.com/project/greeter/quoter"
    assert_built(
        rule_runner,
        Address("", target_name="mod", generated_name="./greeter/quoter"),
        expected_import_paths=[quoter_import_path],
    )

    greeter_import_paths = [
        "example.com/project/greeter",
        quoter_import_path,
        *xerrors_import_paths,
    ]
    assert_built(
        rule_runner,
        Address("", target_name="mod", generated_name="./greeter"),
        expected_import_paths=greeter_import_paths,
    )

    assert_built(
        rule_runner,
        Address("", target_name="mod", generated_name="./"),
        expected_import_paths=["example.com/project", *greeter_import_paths],
    )
