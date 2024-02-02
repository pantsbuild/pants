# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals.tailor import (
    PutativeGoTargetsRequest,
    has_go_mod_ancestor,
    has_package_main,
)
from pants.backend.go.goals.tailor import rules as go_tailor_rules
from pants.backend.go.target_types import GoBinaryTarget, GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    third_party_pkg,
)
from pants.core.goals.tailor import AllOwnedSources, PutativeTarget, PutativeTargets
from pants.core.goals.tailor import rules as core_tailor_rules
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.fs import rules as fs_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *go_tailor_rules(),
            *core_tailor_rules(),
            *go_mod.rules(),
            *first_party_pkg.rules(),
            *third_party_pkg.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *assembly.rules(),
            *link.rules(),
            *fs_rules(),
            *archive_rules(),
            QueryRule(PutativeTargets, [PutativeGoTargetsRequest, AllOwnedSources]),
        ],
        target_types=[
            GoModTarget,
            GoBinaryTarget,
            GoPackageTarget,
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_find_go_mod_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "unowned/go.mod": "module pantsbuild.org/unowned\n",
            "owned/go.mod": "module pantsbuild.org/owned\n",
            "owned/BUILD": "go_mod()",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [PutativeGoTargetsRequest(("unowned", "owned")), AllOwnedSources(["owned/go.mod"])],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoModTarget, path="unowned", name=None, triggering_sources=["go.mod"]
            )
        ]
    )


def test_find_go_package_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "unowned/go.mod": "module pantsbuild.org/unowned\n",
            "unowned/f.go": "",
            "unowned/f1.go": "",
            "unowned/BUILD": "go_mod(name='mod')",
            "owned/go.mod": "module pantsbuild.org/owned\n",
            "owned/f.go": "",
            "owned/BUILD": "go_package()\ngo_mod(name='mod')\n",
            # Any `.go` files under a `testdata` or `vendor` folder should be ignored.
            "unowned/testdata/f.go": "",
            "unowned/testdata/subdir/f.go": "",
            "unowned/vendor/example.com/foo/bar.go": "",
            # Except if `vendor` is the last directory.
            "unowned/cmd/vendor/main.go": "",
            "no_go_mod/f.go": "",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoTargetsRequest(
                (
                    "unowned",
                    "owned",
                    "unowned/testdata",
                    "unowned/vendor",
                    "unowned/cmd/vendor",
                    "no_go_mod",
                )
            ),
            AllOwnedSources(["owned/f.go", "unowned/go.mod", "owned/go.mod"]),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoPackageTarget,
                path="unowned",
                name=None,
                triggering_sources=["f.go", "f1.go"],
            ),
            PutativeTarget.for_target_type(
                GoPackageTarget,
                path="unowned/cmd/vendor",
                name=None,
                triggering_sources=["main.go"],
            ),
        ]
    )


def test_cgo_sources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "go_mod()",
            "foo/go.mod": "module pantsbuild.org/example\n",
            "foo/main.go": "",
            "foo/native.c": "",
            "foo/another.c": "",
            "foo/native.h": "",
            "foo/assembly.s": "",
            "c_only/native.c": "",
            "c_only/assembly.s": "",
            "c_only/header.h": "",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoTargetsRequest(("foo",)),
            AllOwnedSources(["foo/go.mod"]),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoPackageTarget,
                path="foo",
                name=None,
                kwargs={"sources": ("*.go", "*.c", "*.s", "*.h")},
                triggering_sources=["main.go", "another.c", "assembly.s", "native.c", "native.h"],
            ),
        ]
    )


def test_find_go_binary_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "missing_binary_tgt/go.mod": "module pantsbuild.org/missing_binary_tgt\n",
            "missing_binary_tgt/app.go": "package main",
            "missing_binary_tgt/BUILD": "go_package()\ngo_mod(name='mod')\n",
            "tgt_already_exists/go.mod": "module pantsbuild.org/tgt_already_exists\n",
            "tgt_already_exists/app.go": "package main",
            "tgt_already_exists/BUILD": "go_binary(name='bin')\ngo_package()\ngo_mod(name='mod')\n",
            "missing_pkg_and_binary_tgt/go.mod": "module pantsbuild.org/missing_pkg_and_binary_tgt\n",
            "missing_pkg_and_binary_tgt/app.go": "package main",
            "missing_pkg_and_binary_tgt/BUILD": "go_mod(name='mod')\n",
            "main_set_to_different_dir/go.mod": "module pantsbuild.org/main_set_to_different_dir\n",
            "main_set_to_different_dir/subdir/app.go": "package main",
            "main_set_to_different_dir/subdir/BUILD": "go_package()",
            "main_set_to_different_dir/BUILD": "go_binary(main='main_set_to_different_dir/subdir')\ngo_mod(name='mod')",
            "no_go_mod/app.go": "package main",
        }
    )
    putative_targets = rule_runner.request(
        PutativeTargets,
        [
            PutativeGoTargetsRequest(
                (
                    "missing_binary_tgt",
                    "tgt_already_exists",
                    "missing_pkg_and_binary_tgt",
                    "main_set_to_different_dir",
                    "no_go_mod",
                )
            ),
            AllOwnedSources(
                [
                    "missing_binary_tgt/go.mod",
                    "missing_binary_tgt/app.go",
                    "tgt_already_exists/go.mod",
                    "tgt_already_exists/app.go",
                    "missing_pkg_and_binary_tgt/go.mod",
                    "main_set_to_different_dir/go.mod",
                    "main_set_to_different_dir/subdir/app.go",
                ]
            ),
        ],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                GoBinaryTarget,
                path="missing_binary_tgt",
                name="bin",
                triggering_sources=[],
            ),
            PutativeTarget.for_target_type(
                GoPackageTarget,
                path="missing_pkg_and_binary_tgt",
                name="missing_pkg_and_binary_tgt",
                triggering_sources=["app.go"],
                kwargs={},
            ),
            PutativeTarget.for_target_type(
                GoBinaryTarget,
                path="missing_pkg_and_binary_tgt",
                name="bin",
                triggering_sources=[],
            ),
        ]
    )


def test_has_package_main() -> None:
    assert has_package_main(b"package main")
    assert has_package_main(b"package main // comment 1233")
    assert has_package_main(b"\n\npackage main\n")
    assert not has_package_main(b"package foo")
    assert not has_package_main(b'var = "package main"')
    assert not has_package_main(b"   package main")


def test_has_go_mod_ancestor() -> None:
    assert has_go_mod_ancestor("dir/subdir", frozenset({"dir/subdir"})) is True
    assert has_go_mod_ancestor("dir/subdir", frozenset({"dir/subdir/child"})) is False
    assert has_go_mod_ancestor("dir/subdir", frozenset({"dir/another"})) is False
    assert has_go_mod_ancestor("dir/subdir", frozenset({""})) is True
    assert has_go_mod_ancestor("dir/subdir", frozenset({"another", "dir/another", "dir"})) is True
