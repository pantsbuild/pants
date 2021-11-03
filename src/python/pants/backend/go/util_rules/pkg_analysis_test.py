# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import textwrap

import pytest

from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    pkg_analysis,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.backend.go.util_rules.pkg_analysis import (
    AnalyzedGoPackage,
    AnalyzedGoPackages,
    AnalyzeGoPackagesRequest,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *pkg_analysis.rules(),
            *assembly.rules(),
            *build_pkg.rules(),
            *import_analysis.rules(),
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *tests_analysis.rules(),
            *link.rules(),
            *sdk.rules(),
            QueryRule(AnalyzedGoPackages, [AnalyzeGoPackagesRequest]),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_basic_package(rule_runner: RuleRunner) -> None:
    ss = rule_runner.make_snapshot(
        {
            "pkg/foo.go": textwrap.dedent(
                """
            package foo
            import "fmt"
            func grok() string {
                fmt.Println("Hello World!")
            }
            """
            )
        }
    )

    result = rule_runner.request(
        AnalyzedGoPackages, [AnalyzeGoPackagesRequest(ss.digest, ("pkg",))]
    )
    assert result == AnalyzedGoPackages(
        FrozenDict(
            {
                "pkg": AnalyzedGoPackage(
                    name="foo",
                    imports=("fmt",),
                    test_imports=(),
                    xtest_imports=(),
                    go_files=("foo.go",),
                    s_files=(),
                    ignored_go_files=(),
                    ignored_other_files=(),
                    test_go_files=(),
                    xtest_go_files=(),
                    invalid_go_files=FrozenDict(),
                    error=None,
                )
            }
        )
    )
