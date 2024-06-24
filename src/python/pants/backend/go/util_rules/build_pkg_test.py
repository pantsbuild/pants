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
    first_party_pkg,
    go_mod,
    import_analysis,
    link,
    sdk,
    third_party_pkg,
)
from pants.backend.go.util_rules.build_opts import GoBuildOptions
from pants.backend.go.util_rules.build_pkg import (
    BuildGoPackageRequest,
    BuiltGoPackage,
    FallibleBuiltGoPackage,
)
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.fs import Snapshot
from pants.engine.fs import rules as fs_rules
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
            *import_analysis.rules(),
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *link.rules(),
            *third_party_pkg.rules(),
            *target_type_rules.rules(),
            *fs_rules(),
            *archive_rules(),
            QueryRule(BuiltGoPackage, [BuildGoPackageRequest]),
            QueryRule(FallibleBuiltGoPackage, [BuildGoPackageRequest]),
        ],
        target_types=[GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def assert_built(
    rule_runner: RuleRunner, request: BuildGoPackageRequest, *, expected_import_paths: list[str]
) -> None:
    built_package = rule_runner.request(BuiltGoPackage, [request])
    result_files = rule_runner.request(Snapshot, [built_package.digest]).files
    expected = {
        import_path: os.path.join("__pkgs__", path_safe(import_path), "__pkg__.a")
        for import_path in expected_import_paths
    }
    assert dict(built_package.import_paths_to_pkg_a_files) == expected
    assert sorted(result_files) == sorted(expected.values())


def test_build_pkg(rule_runner: RuleRunner) -> None:
    transitive_dep = BuildGoPackageRequest(
        import_path="example.com/foo/dep/transitive",
        pkg_name="transitive",
        dir_path="dep/transitive",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=rule_runner.make_snapshot(
            {
                "dep/transitive/f.go": dedent(
                    """\
                    package transitive

                    func Quote(s string) string {
                        return ">>" + s + "<<"
                    }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(),
        minimum_go_version=None,
    )
    direct_dep = BuildGoPackageRequest(
        import_path="example.com/foo/dep",
        pkg_name="dep",
        dir_path="dep",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=rule_runner.make_snapshot(
            {
                "dep/f.go": dedent(
                    """\
                    package dep

                    import "example.com/foo/dep/transitive"

                    func Quote(s string) string {
                        return transitive.Quote(s)
                    }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(transitive_dep,),
        minimum_go_version=None,
    )
    main = BuildGoPackageRequest(
        import_path="example.com/foo",
        pkg_name="foo",
        dir_path="",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=rule_runner.make_snapshot(
            {
                "f.go": dedent(
                    """\
                    package foo

                    import "example.com/foo/dep"

                    func main() {
                        dep.Quote("Hello world!")
                    }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(direct_dep,),
        minimum_go_version=None,
    )

    assert_built(
        rule_runner, transitive_dep, expected_import_paths=["example.com/foo/dep/transitive"]
    )
    assert_built(
        rule_runner,
        direct_dep,
        expected_import_paths=["example.com/foo/dep", "example.com/foo/dep/transitive"],
    )
    assert_built(
        rule_runner,
        main,
        expected_import_paths=[
            "example.com/foo",
            "example.com/foo/dep",
            "example.com/foo/dep/transitive",
        ],
    )


def test_build_invalid_pkg(rule_runner: RuleRunner) -> None:
    invalid_dep = BuildGoPackageRequest(
        import_path="example.com/foo/dep",
        pkg_name="dep",
        dir_path="dep",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=rule_runner.make_snapshot({"dep/f.go": "invalid!!!"}).digest,
        s_files=(),
        direct_dependencies=(),
        minimum_go_version=None,
    )
    main = BuildGoPackageRequest(
        import_path="example.com/foo",
        pkg_name="main",
        dir_path="",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=rule_runner.make_snapshot(
            {
                "f.go": dedent(
                    """\
                    package main

                    import "example.com/foo/dep"

                    func main() {
                        dep.Quote("Hello world!")
                    }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(invalid_dep,),
        minimum_go_version=None,
    )

    invalid_direct_result = rule_runner.request(FallibleBuiltGoPackage, [invalid_dep])
    assert invalid_direct_result.output is None
    assert invalid_direct_result.exit_code == 1
    assert (
        invalid_direct_result.stdout
        == "dep/f.go:1:1: syntax error: package statement must be first\n"
    )

    invalid_dep_result = rule_runner.request(FallibleBuiltGoPackage, [main])
    assert invalid_dep_result.output is None
    assert invalid_dep_result.exit_code == 1
    assert (
        invalid_dep_result.stdout == "dep/f.go:1:1: syntax error: package statement must be first\n"
    )
