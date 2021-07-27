# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.backend.go import module, pkg
from pants.backend.go.pkg import ResolvedGoPackage, ResolveGoPackageRequest
from pants.backend.go.target_types import GoExternalModule, GoModule, GoPackage
from pants.build_graph.address import Address
from pants.core.util_rules import external_tool, source_files
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *module.rules(),
            *pkg.rules(),
            QueryRule(ResolvedGoPackage, [ResolveGoPackageRequest]),
        ],
        target_types=[GoPackage, GoModule, GoExternalModule],
    )
    rule_runner.set_options(["--backend-packages=pants.backend.experimental.go"])
    return rule_runner


def test_resolve_go_module(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_module()\n",
            "foo/go.mod": textwrap.dedent(
                """\
                module go.example.com/foo
                go 1.16"""
            ),
            "foo/go.sum": "",
            "foo/pkg/BUILD": "go_package()\n",
            "foo/pkg/foo.go": textwrap.dedent(
                """\
                package pkg
                func Grok() string {
                    return "Hello World"
                }"""
            ),
            "foo/cmd/BUILD": "go_package()\n",
            "foo/cmd/main.go": textwrap.dedent(
                """\
                package main
                import (
                    "fmt"
                    "go.example.com/foo/pkg"
                )
                func main() {
                    fmt.Printf("%s\n", pkg.Grok())
                }"""
            ),
        }
    )
    resolved_go_package = rule_runner.request(
        ResolvedGoPackage, [ResolveGoPackageRequest(Address("foo/cmd"))]
    )
    assert resolved_go_package.import_path == "go.example.com/foo/cmd"
