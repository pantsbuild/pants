# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os.path
from dataclasses import dataclass
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
    _gather_transitive_prebuilt_object_files,
)
from pants.engine.fs import Snapshot
from pants.engine.rules import QueryRule, rule
from pants.testutil.rule_runner import RuleRunner
from pants.util.strutil import path_safe


# ---------------------------------------------------------------------------
# Test-only rule for probing _gather_transitive_prebuilt_object_files directly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GatherPrebuiltObjectFilesResult:
    object_files: frozenset[str]


@rule
async def _gather_prebuilt_object_files_for_test(
    request: BuildGoPackageRequest,
) -> _GatherPrebuiltObjectFilesResult:
    _, object_files = await _gather_transitive_prebuilt_object_files(request)
    return _GatherPrebuiltObjectFilesResult(object_files)


def _syso_test_rules():
    return [
        _gather_prebuilt_object_files_for_test,
        QueryRule(_GatherPrebuiltObjectFilesResult, [BuildGoPackageRequest]),
    ]


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
            QueryRule(BuiltGoPackage, [BuildGoPackageRequest]),
            QueryRule(FallibleBuiltGoPackage, [BuildGoPackageRequest]),
        ],
        target_types=[GoModTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


@pytest.fixture
def syso_rule_runner() -> RuleRunner:
    """Fixture that includes the test-only rule for probing _gather_transitive_prebuilt_object_files."""
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
            *_syso_test_rules(),
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
        minimum_go_version="1.21.2",
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


def test_gather_transitive_prebuilt_object_files_depth2(syso_rule_runner: RuleRunner) -> None:
    """Regression test for BFS bug in _gather_transitive_prebuilt_object_files.

    Before the fix, line 549 read:
        unseen = [dd for dd in build_request.direct_dependencies if dd not in seen]
    which always expanded the *root's* direct deps instead of the *current node's*
    direct deps.  As a result, the BFS never descended past depth 1 and any
    `.syso` file belonging to a grandchild (or deeper) dependency was silently
    dropped from cgo linking.

    This test constructs the minimal chain that exposes the bug:
        cgo_root → direct_dep → grandchild  (grandchild has prebuilt_object_files)

    With the bug present, `_gather_transitive_prebuilt_object_files(cgo_root)`
    returns an empty `object_files` set because it only ever enqueues
    `cgo_root.direct_dependencies` (i.e., `[direct_dep]`) on every iteration
    rather than the *current* node's deps, so `grandchild` is never visited.
    With the fix, `pkg.direct_dependencies` correctly enqueues `grandchild`
    from `direct_dep`, and the `.syso` path is returned.
    """
    grandchild = BuildGoPackageRequest(
        import_path="example.com/foo/grandchild",
        pkg_name="grandchild",
        dir_path="grandchild",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=syso_rule_runner.make_snapshot(
            {
                "grandchild/f.go": dedent(
                    """\
                    package grandchild

                    func Value() int { return 1 }
                    """
                ),
                # Fake .syso bytes: the BFS only needs the file path recorded in
                # prebuilt_object_files; actual content is irrelevant for this test.
                "grandchild/helper.syso": b"\x00",
            }
        ).digest,
        s_files=(),
        direct_dependencies=(),
        minimum_go_version=None,
        prebuilt_object_files=("helper.syso",),
    )
    direct_dep = BuildGoPackageRequest(
        import_path="example.com/foo/dep",
        pkg_name="dep",
        dir_path="dep",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=syso_rule_runner.make_snapshot(
            {
                "dep/f.go": dedent(
                    """\
                    package dep

                    import "example.com/foo/grandchild"

                    func Value() int { return grandchild.Value() }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(grandchild,),
        minimum_go_version=None,
    )
    cgo_root = BuildGoPackageRequest(
        import_path="example.com/foo",
        pkg_name="foo",
        dir_path="",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=syso_rule_runner.make_snapshot(
            {
                "f.go": dedent(
                    """\
                    package foo

                    import "example.com/foo/dep"

                    func Root() int { return dep.Value() }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(direct_dep,),
        minimum_go_version=None,
    )

    result = syso_rule_runner.request(_GatherPrebuiltObjectFilesResult, [cgo_root])

    # The grandchild's .syso must be present even though it is at depth 2.
    assert os.path.join("grandchild", "helper.syso") in result.object_files, (
        f"grandchild/helper.syso missing from collected object_files={result.object_files!r}; "
        "BFS bug: _gather_transitive_prebuilt_object_files never visited the grandchild node"
    )
