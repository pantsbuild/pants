# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import go_mod, sdk
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.build_graph.address import Address
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.fs import rules as fs_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            *go_mod.rules(),
            *fs_rules(),
            *archive_rules(),
            QueryRule(OwningGoMod, [OwningGoModRequest]),
            QueryRule(GoModInfo, [GoModInfoRequest]),
        ],
        target_types=[GoModTarget, GoPackageTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_owning_go_mod(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "go.mod": "",
            "f.go": "",
            "BUILD": "go_mod(name='mod')\ngo_package(name='pkg')",
            "dir/f.go": "",
            "dir/BUILD": "go_package()",
            "dir/subdir/go.mod": "",
            "dir/subdir/BUILD": "go_mod(name='mod')\ngo_package()",
            "dir/subdir/f.go": "",
            "dir/subdir/another/f.go": "",
            "dir/subdir/another/BUILD": "go_package()",
        }
    )

    def assert_owner(pkg: Address, mod: Address) -> None:
        owner = rule_runner.request(OwningGoMod, [OwningGoModRequest(pkg)])
        assert owner.address == mod

    assert_owner(Address("", target_name="pkg"), Address("", target_name="mod"))
    assert_owner(Address("dir"), Address("", target_name="mod"))
    assert_owner(Address("dir/subdir"), Address("dir/subdir", target_name="mod"))
    assert_owner(Address("dir/subdir/another"), Address("dir/subdir", target_name="mod"))


def test_go_mod_info(rule_runner: RuleRunner) -> None:
    go_mod_content = dedent(
        """\
        module go.example.com/foo
        go 1.17
        require github.com/golang/protobuf v1.4.2
        """
    )
    go_sum_content = "does not matter"
    rule_runner.write_files(
        {"foo/go.mod": go_mod_content, "foo/go.sum": go_sum_content, "foo/BUILD": "go_mod()"}
    )
    go_mod_info = rule_runner.request(GoModInfo, [GoModInfoRequest(Address("foo"))])
    assert go_mod_info.import_path == "go.example.com/foo"
    assert (
        go_mod_info.digest
        == rule_runner.make_snapshot(
            {"foo/go.mod": go_mod_content, "foo/go.sum": go_sum_content}
        ).digest
    )
    assert go_mod_info.mod_path == "foo/go.mod"
    assert go_mod_info.minimum_go_version == "1.17"
