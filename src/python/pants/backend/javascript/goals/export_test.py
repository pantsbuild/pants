# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from pathlib import Path

import pytest

from pants.backend.javascript import install_node_package
from pants.backend.javascript.goals import export
from pants.backend.javascript.goals.export import ExportNodeModulesRequest
from pants.backend.javascript.package_json import PackageJsonTarget
from pants.base.specs import RawSpecs
from pants.core.goals.export import ExportResults
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.rules import QueryRule
from pants.engine.target import (
    Targets,
)
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *export.rules(),
            *install_node_package.rules(),
            QueryRule(Targets, [RawSpecs]),
            QueryRule(ExportResults, [ExportNodeModulesRequest]),
            QueryRule(Snapshot, [Digest])
        ],
        target_types=[PackageJsonTarget],
    )


def given_package_with_name(name: str) -> str:
    return json.dumps({"name": name, "version": "0.0.1", "devDependencies": {"jest": "*"}})


def get_snapshot(rule_runner: RuleRunner, digest: Digest) -> Snapshot:
    return rule_runner.request(Snapshot, [digest])


def test_export_node_modules(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--export-resolve=nodejs-default"], env_inherit={"PATH"})
    rule_runner.write_files(
        {
            "BUILD": "package_json(name='root')",
            "package-lock.json": (Path(__file__).parent / "jest_resources/package-lock.json").read_text(),
            "package.json": given_package_with_name("ham"),
        }
    )
    results = rule_runner.request(ExportResults, [ExportNodeModulesRequest(tuple())])
    assert len(results) == 1
    result = results[0]

    snapshot = get_snapshot(rule_runner, result.digest)

    assert result.resolve == 'nodejs-default'
    assert 'node_modules/jest' in snapshot.dirs
