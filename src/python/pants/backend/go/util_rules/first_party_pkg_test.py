# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.target_types import GoModTarget
from pants.backend.go.util_rules import first_party_pkg, go_mod, sdk, third_party_pkg
from pants.backend.go.util_rules.first_party_pkg import (
    FallibleFirstPartyPkgInfo,
    FirstPartyPkgInfoRequest,
)
from pants.engine.addresses import Address
from pants.engine.fs import PathGlobs, Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner, engine_error


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *sdk.rules(),
            *third_party_pkg.rules(),
            *target_type_rules.rules(),
            QueryRule(FallibleFirstPartyPkgInfo, [FirstPartyPkgInfoRequest]),
        ],
        target_types=[GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_package_info(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod()\n",
            "foo/go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.16
                require github.com/google/uuid v1.3.0
                require (
                    rsc.io/quote v1.5.2
                    golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c // indirect
                    rsc.io/sampler v1.3.0 // indirect
                )
                """
            ),
            "foo/go.sum": dedent(
                """\
                github.com/google/uuid v1.3.0 h1:t6JiXgmwXMjEs8VusXIJk2BXHsn+wx8BZdTaoZ5fu7I=
                github.com/google/uuid v1.3.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
                golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c h1:qgOY6WgZOaTkIIMiVjBQcw93ERBE4m30iBm00nkL0i8=
                golang.org/x/text v0.0.0-20170915032832-14c0d48ead0c/go.mod h1:NqM8EUOU14njkJ3fqMW+pc6Ldnwhi/IjpwHt7yyuwOQ=
                rsc.io/quote v1.5.2 h1:w5fcysjrx7yqtD/aO+QwRjYZOKnaM9Uh2b40tElTs3Y=
                rsc.io/quote v1.5.2/go.mod h1:LzX7hefJvL54yjefDEDHNONDjII0t9xZLPXsUe+TKr0=
                rsc.io/sampler v1.3.0 h1:7uVkIFmeBqHfdjD+gZwtXXI+RODJ2Wc4O7MPEh/QiW4=
                rsc.io/sampler v1.3.0/go.mod h1:T1hPZKmBbMNahiBKFy5HrXp6adAjACjK9JXDnKaTXpA=
                """
            ),
            "foo/pkg/foo.go": dedent(
                """\
                package pkg
                import "github.com/google/uuid"
                import "rsc.io/quote"

                func Grok() string {
                    return "Hello World"
                }
                """
            ),
            "foo/cmd/main.go": dedent(
                """\
                package main
                import (
                    "fmt"
                    "go.example.com/foo/pkg"
                )
                func main() {
                    fmt.Printf("%s\n", pkg.Grok())
                }
                """
            ),
            "foo/cmd/bar_test.go": dedent(
                """\
                package main
                import "testing"
                func TestBar(t *testing.T) {}
                """
            ),
        }
    )

    def assert_info(
        subpath: str,
        *,
        imports: list[str],
        test_imports: list[str],
        xtest_imports: list[str],
        go_files: list[str],
        test_files: list[str],
        xtest_files: list[str],
    ) -> None:
        maybe_info = rule_runner.request(
            FallibleFirstPartyPkgInfo,
            [FirstPartyPkgInfoRequest(Address("foo", generated_name=f"./{subpath}"))],
        )
        assert maybe_info.info is not None
        info = maybe_info.info
        actual_snapshot = rule_runner.request(Snapshot, [info.digest])
        expected_snapshot = rule_runner.request(Snapshot, [PathGlobs([f"foo/{subpath}/*.go"])])
        assert actual_snapshot == expected_snapshot

        assert info.imports == tuple(imports)
        assert info.test_imports == tuple(test_imports)
        assert info.xtest_imports == tuple(xtest_imports)
        assert info.go_files == tuple(go_files)
        assert info.test_files == tuple(test_files)
        assert info.xtest_files == tuple(xtest_files)
        assert not info.s_files

    assert_info(
        "pkg",
        imports=["github.com/google/uuid", "rsc.io/quote"],
        test_imports=[],
        xtest_imports=[],
        go_files=["foo.go"],
        test_files=[],
        xtest_files=[],
    )
    assert_info(
        "cmd",
        imports=["fmt", "go.example.com/foo/pkg"],
        test_imports=["testing"],
        xtest_imports=[],
        go_files=["main.go"],
        test_files=["bar_test.go"],
        xtest_files=[],
    )


def test_invalid_package(rule_runner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "go_mod(name='mod')\n",
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            "bad.go": "invalid!!!",
        }
    )
    maybe_info = rule_runner.request(
        FallibleFirstPartyPkgInfo,
        [FirstPartyPkgInfoRequest(Address("", target_name="mod", generated_name="./"))],
    )
    assert maybe_info.info is None
    assert maybe_info.exit_code == 1
    assert maybe_info.stderr == "bad.go:1:1: expected 'package', found invalid\n"


def test_cgo_not_supported(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "go_mod(name='mod')\n",
            "go.mod": dedent(
                """\
                module go.example.com/foo
                go 1.17
                """
            ),
            "hello.go": dedent(
                """\
                package main

                // int fortytwo()
                // {
                //	    return 42;
                // }
                import "C"
                import "fmt"

                func main() {
                    f := C.intFunc(C.fortytwo)
                    fmt.Println(C.intFunc(C.fortytwo))
                }
                """
            ),
        }
    )
    with engine_error(NotImplementedError):
        rule_runner.request(
            FallibleFirstPartyPkgInfo,
            [FirstPartyPkgInfoRequest(Address("", target_name="mod", generated_name="./"))],
        )
