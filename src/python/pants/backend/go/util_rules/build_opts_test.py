# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.go.target_types import GoBinaryTarget, GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import build_opts
from pants.backend.go.util_rules.build_opts import GoBuildOptions, GoBuildOptionsFromTargetRequest
from pants.build_graph.address import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *build_opts.rules(),
            QueryRule(GoBuildOptions, (GoBuildOptionsFromTargetRequest,)),
        ],
        target_types=[GoModTarget, GoPackageTarget, GoBinaryTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_race_detector_fields_work_as_expected(rule_runner: RuleRunner) -> None:
    def module_files(dir_path: str, value: bool | None) -> dict:
        race_field = f", race={value}" if value is not None else ""
        return {
            f"{dir_path}/BUILD": dedent(
                f"""\
            go_mod(name="mod"{race_field})
            go_package(name="pkg")
            go_binary(name="bin_with_race_unspecified")
            go_binary(name="bin_with_race_false", race=False)
            go_binary(name="bin_with_race_true", race=True)
            """
            ),
            f"{dir_path}/go.mod": f"module test.pantsbuild.org/{dir_path}\n",
            f"{dir_path}/main.go": dedent(
                """\
            package main
            func main() {}
            """
            ),
            f"{dir_path}/pkg_race_false/BUILD": "go_package(test_race=False)\n",
            f"{dir_path}/pkg_race_false/foo.go": "package pkg_race_false\n",
            f"{dir_path}/pkg_race_true/BUILD": "go_package(test_race=True)\n",
            f"{dir_path}/pkg_race_true/foo.go": "package pkg_race_true\n",
        }

    rule_runner.write_files(
        {
            **module_files("mod_race_unspecified", None),
            **module_files("mod_race_false", False),
            **module_files("mod_race_true", True),
        }
    )

    def assert_value(
        address: Address, expected_value: bool, *, for_tests: bool = False, msg: str
    ) -> None:
        opts = rule_runner.request(
            GoBuildOptions,
            (GoBuildOptionsFromTargetRequest(address=address, for_tests=for_tests),),
        )
        assert (
            opts.with_race_detector is expected_value
        ), f"{address}: expected {expected_value} {msg}"

    # go_mod does not specify a value for `race`
    assert_value(
        Address("mod_race_unspecified", target_name="bin_with_race_unspecified"),
        False,
        msg="when unspecified on go_binary and when unspecified on go_mod",
    )
    assert_value(
        Address("mod_race_unspecified", target_name="bin_with_race_false"),
        False,
        msg="when race=False on go_binary and when unspecified on go_mod",
    )
    assert_value(
        Address("mod_race_unspecified", target_name="bin_with_race_true"),
        True,
        msg="when race=True on go_binary and when unspecified on go_mod",
    )
    assert_value(
        Address("mod_race_unspecified", target_name="pkg"),
        False,
        for_tests=True,
        msg="for go_package when unspecified on go_mod",
    )
    assert_value(
        Address("mod_race_unspecified/pkg_race_false"),
        False,
        for_tests=True,
        msg="for go_package(test_race=False) when unspecified on go_mod",
    )
    assert_value(
        Address("mod_race_unspecified/pkg_race_true"),
        True,
        for_tests=True,
        msg="for go_package(test_race=True) when unspecified on go_mod",
    )
    assert_value(
        Address("mod_race_unspecified", target_name="mod"),
        False,
        msg="for go_mod when unspecified on go_mod",
    )

    # go_mod specifies False for `race`
    assert_value(
        Address("mod_race_false", target_name="bin_with_race_unspecified"),
        False,
        msg="when unspecified on go_binary and when race=False on go_mod",
    )
    assert_value(
        Address("mod_race_false", target_name="bin_with_race_false"),
        False,
        msg="when race=False on go_binary and when race=False on go_mod",
    )
    assert_value(
        Address("mod_race_false", target_name="bin_with_race_true"),
        True,
        msg="when race=True on go_binary and when race=False on go_mod",
    )
    assert_value(
        Address("mod_race_false", target_name="pkg"),
        False,
        for_tests=True,
        msg="for go_package when race=False on go_mod",
    )
    assert_value(
        Address("mod_race_false/pkg_race_false"),
        False,
        for_tests=True,
        msg="for go_package(test_race=False) when race=False on go_mod",
    )
    assert_value(
        Address("mod_race_false/pkg_race_true"),
        True,
        for_tests=True,
        msg="for go_package(test_race=True) when race=False on go_mod",
    )
    assert_value(
        Address("mod_race_false", target_name="mod"),
        False,
        msg="for go_mod when race=False on go_mod",
    )

    # go_mod specifies True for `race`
    assert_value(
        Address("mod_race_true", target_name="bin_with_race_unspecified"),
        True,
        msg="when unspecified on go_binary and when race=True on go_mod",
    )
    assert_value(
        Address("mod_race_true", target_name="bin_with_race_false"),
        False,
        msg="when race=False on go_binary and when race=True on go_mod",
    )
    assert_value(
        Address("mod_race_true", target_name="bin_with_race_true"),
        True,
        msg="when race=True on go_binary and when race=True on go_mod",
    )
    assert_value(
        Address("mod_race_true", target_name="pkg"),
        True,
        for_tests=True,
        msg="for go_package when race=True on go_mod",
    )
    assert_value(
        Address("mod_race_true/pkg_race_false"),
        False,
        for_tests=True,
        msg="for go_package(test_race=False) when race=True on go_mod",
    )
    assert_value(
        Address("mod_race_true/pkg_race_true"),
        True,
        for_tests=True,
        msg="for go_package(test_race=True) when race=True on go_mod",
    )
    assert_value(
        Address("mod_race_true", target_name="mod"),
        True,
        msg="for go_mod when race=True on go_mod",
    )

    # Test when `--go-test-force-race` is in effect.
    rule_runner.set_options(["--go-test-force-race"], env_inherit={"PATH"})
    assert_value(
        Address("mod_race_unspecified", target_name="pkg"),
        True,
        for_tests=True,
        msg="for go_package when --go-test-force-race and when unspecified on go_mod",
    )
    assert_value(
        Address("mod_race_false", target_name="pkg"),
        True,
        for_tests=True,
        msg="for go_package when --go-test-force-race and when race=False on go_mod",
    )
