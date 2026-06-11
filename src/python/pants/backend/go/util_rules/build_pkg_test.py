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
    MergeBuiltGoPackageArchivesRequest,
    MergedGoPackageArchives,
    _gather_transitive_prebuilt_object_files,
)
from pants.engine.fs import Snapshot
from pants.engine.rules import QueryRule, rule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict
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
            QueryRule(MergedGoPackageArchives, [MergeBuiltGoPackageArchivesRequest]),
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
    own_files = rule_runner.request(Snapshot, [built_package.archive_digest]).files
    expected = {
        import_path: os.path.join("__pkgs__", path_safe(import_path), "__pkg__.a")
        for import_path in expected_import_paths
    }
    assert built_package.pkg_archive_path == os.path.join(
        "__pkgs__", path_safe(built_package.import_path), "__pkg__.a"
    )
    assert sorted(own_files) == [built_package.pkg_archive_path]
    assert {ip: path for ip, (path, _) in built_package.transitive_pkg_archives.items()} == expected


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


def test_build_pkg_deep_chain(rule_runner: RuleRunner) -> None:
    """A 4-level dependency chain compiles with direct-deps-only compile inputs.

    `a → b → c → d`: `d` defines an exported struct, `c` wraps it, `b` re-exports a function
    returning the wrapper, and `a` reaches through to the innermost field.  Compiling `a` only
    has `b`'s export data in its importcfg, so this exercises the self-containedness of gc
    export data across multiple levels (the canary for the direct-deps-only premise).
    """
    pkg_d = BuildGoPackageRequest(
        import_path="example.com/deep/d",
        pkg_name="d",
        dir_path="d",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=rule_runner.make_snapshot(
            {
                "d/f.go": dedent(
                    """\
                    package d

                    type Thing struct {
                        Value int
                    }

                    func New() Thing {
                        return Thing{Value: 42}
                    }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(),
        minimum_go_version=None,
    )
    pkg_c = BuildGoPackageRequest(
        import_path="example.com/deep/c",
        pkg_name="c",
        dir_path="c",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=rule_runner.make_snapshot(
            {
                "c/f.go": dedent(
                    """\
                    package c

                    import "example.com/deep/d"

                    type Wrapped struct {
                        Inner d.Thing
                    }

                    func Get() Wrapped {
                        return Wrapped{Inner: d.New()}
                    }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(pkg_d,),
        minimum_go_version=None,
    )
    pkg_b = BuildGoPackageRequest(
        import_path="example.com/deep/b",
        pkg_name="b",
        dir_path="b",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=rule_runner.make_snapshot(
            {
                "b/f.go": dedent(
                    """\
                    package b

                    import "example.com/deep/c"

                    func Get() c.Wrapped {
                        return c.Get()
                    }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(pkg_c,),
        minimum_go_version=None,
    )
    pkg_a = BuildGoPackageRequest(
        import_path="example.com/deep/a",
        pkg_name="a",
        dir_path="a",
        build_opts=GoBuildOptions(),
        go_files=("f.go",),
        digest=rule_runner.make_snapshot(
            {
                "a/f.go": dedent(
                    """\
                    package a

                    import "example.com/deep/b"

                    func Use() int {
                        return b.Get().Inner.Value
                    }
                    """
                )
            }
        ).digest,
        s_files=(),
        direct_dependencies=(pkg_b,),
        minimum_go_version=None,
    )

    all_import_paths = [
        "example.com/deep/a",
        "example.com/deep/b",
        "example.com/deep/c",
        "example.com/deep/d",
    ]

    built_a = rule_runner.request(BuiltGoPackage, [pkg_a])

    # The package's own digest contains only its own archive.
    own_files = rule_runner.request(Snapshot, [built_a.archive_digest]).files
    assert sorted(own_files) == [built_a.pkg_archive_path]

    # The transitive handle map covers the full closure.
    assert set(built_a.transitive_pkg_archives.keys()) == set(all_import_paths)

    # Merging the closure of (a,) yields all four archives, each exactly once.
    merged = rule_runner.request(
        MergedGoPackageArchives, [MergeBuiltGoPackageArchivesRequest((built_a,))]
    )
    expected_paths = {
        import_path: os.path.join("__pkgs__", path_safe(import_path), "__pkg__.a")
        for import_path in all_import_paths
    }
    assert dict(merged.import_paths_to_pkg_a_files) == expected_paths
    merged_files = rule_runner.request(Snapshot, [merged.digest]).files
    assert sorted(merged_files) == sorted(expected_paths.values())


def test_merge_built_go_package_archives(rule_runner: RuleRunner) -> None:
    """Overlapping transitive maps merge each archive once, first-wins on conflicts."""
    digest_a = rule_runner.make_snapshot({"__pkgs__/a/__pkg__.a": "a-archive"}).digest
    digest_b = rule_runner.make_snapshot({"__pkgs__/b/__pkg__.a": "b-archive"}).digest
    digest_common = rule_runner.make_snapshot({"__pkgs__/common/__pkg__.a": "common"}).digest
    digest_shared_v1 = rule_runner.make_snapshot({"__pkgs__/shared/__pkg__.a": "shared-v1"}).digest
    digest_shared_v2 = rule_runner.make_snapshot(
        {"__pkgs__/shared_v2/__pkg__.a": "shared-v2"}
    ).digest

    path_a = os.path.join("__pkgs__", "a", "__pkg__.a")
    path_b = os.path.join("__pkgs__", "b", "__pkg__.a")
    path_common = os.path.join("__pkgs__", "common", "__pkg__.a")
    path_shared_v1 = os.path.join("__pkgs__", "shared", "__pkg__.a")
    path_shared_v2 = os.path.join("__pkgs__", "shared_v2", "__pkg__.a")

    pkg_one = BuiltGoPackage(
        import_path="example.com/a",
        pkg_archive_path=path_a,
        archive_digest=digest_a,
        transitive_pkg_archives=FrozenDict(
            {
                "example.com/a": (path_a, digest_a),
                "example.com/common": (path_common, digest_common),
                "example.com/shared": (path_shared_v1, digest_shared_v1),
            }
        ),
    )
    pkg_two = BuiltGoPackage(
        import_path="example.com/b",
        pkg_archive_path=path_b,
        archive_digest=digest_b,
        transitive_pkg_archives=FrozenDict(
            {
                "example.com/b": (path_b, digest_b),
                # Identical entry in both packages: must merge cleanly, exactly once.
                "example.com/common": (path_common, digest_common),
                # Conflicting entry: pkg_one came first, so its handle must win.
                "example.com/shared": (path_shared_v2, digest_shared_v2),
            }
        ),
    )

    merged = rule_runner.request(
        MergedGoPackageArchives, [MergeBuiltGoPackageArchivesRequest((pkg_one, pkg_two))]
    )

    assert dict(merged.import_paths_to_pkg_a_files) == {
        "example.com/a": path_a,
        "example.com/b": path_b,
        "example.com/common": path_common,
        "example.com/shared": path_shared_v1,
    }
    merged_files = rule_runner.request(Snapshot, [merged.digest]).files
    assert sorted(merged_files) == sorted([path_a, path_b, path_common, path_shared_v1])


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
