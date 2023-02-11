# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
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

    assert a_result == ChosenNodeResolve(
        resolve_name="src.js.a", file_path="src/js/a/package-lock.json"
    )
    assert b_result == ChosenNodeResolve(
        resolve_name="src.js.b", file_path="src/js/b/package-lock.json"
    )


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

    expected_resolve = ChosenNodeResolve(
        resolve_name="src.js", file_path="src/js/package-lock.json"
    )

    tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    result = rule_runner.request(ChosenNodeResolve, [RequestNodeResolve(tgt.address)])

    child_tgt = rule_runner.get_target(Address("src/js/child", generated_name="spam"))
    child_result = rule_runner.request(ChosenNodeResolve, [RequestNodeResolve(child_tgt.address)])

    assert child_result == result == expected_resolve
