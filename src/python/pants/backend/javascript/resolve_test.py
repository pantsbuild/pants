# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json

import pytest

from pants.backend.javascript import resolve
from pants.backend.javascript.package_json import NodeThirdPartyPackageTarget, PackageJsonTarget
from pants.backend.javascript.resolve import ChosenNodeResolve, RequestNodeResolve
from pants.build_graph.address import Address
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *resolve.rules(),
            QueryRule(ChosenNodeResolve, (RequestNodeResolve,)),
        ],
        target_types=[
            PackageJsonTarget,
            NodeThirdPartyPackageTarget,
            TargetGeneratorSourcesHelperTarget,
        ],
    )


def test_gets_expected_resolve_for_standalone_packages(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": json.dumps({"name": "ham", "version": "0.0.1"}),
            "src/js/b/BUILD": "package_json()",
            "src/js/b/package.json": json.dumps({"name": "spam", "version": "0.0.1"}),
        }
    )
    a_tgt = rule_runner.get_target(Address("src/js/a", generated_name="ham"))
    b_tgt = rule_runner.get_target(Address("src/js/b", generated_name="spam"))

    a_result = rule_runner.request(ChosenNodeResolve, [RequestNodeResolve(a_tgt.address)])
    b_result = rule_runner.request(ChosenNodeResolve, [RequestNodeResolve(b_tgt.address)])

    assert a_result.resolve_name == "js.a"
    assert a_result.file_path == "src/js/a/package-lock.json"
    assert b_result.resolve_name == "js.b"
    assert b_result.file_path == "src/js/b/package-lock.json"


def test_gets_expected_resolve_for_workspace_packages(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": json.dumps(
                {"name": "ham", "version": "0.0.1", "workspaces": ["./child"]}
            ),
            "src/js/child/BUILD": "package_json()",
            "src/js/child/package.json": json.dumps({"name": "spam", "version": "0.0.1"}),
        }
    )

    tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    result = rule_runner.request(ChosenNodeResolve, [RequestNodeResolve(tgt.address)])

    child_tgt = rule_runner.get_target(Address("src/js/child", generated_name="spam"))
    child_result = rule_runner.request(ChosenNodeResolve, [RequestNodeResolve(child_tgt.address)])

    assert child_result == result
    assert child_result.resolve_name == "js"
    assert child_result.file_path == "src/js/package-lock.json"
