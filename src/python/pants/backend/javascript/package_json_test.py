# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import (
    AllPackageJson,
    PackageJson,
    PackageJsonTarget,
)
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *package_json.rules(),
            QueryRule(AllPackageJson, ())
        ],
        target_types=[PackageJsonTarget],
    )


def given_package(name: str, version: str) -> str:
    return json.dumps({"name": name, "version": version})


def test_parses_package_jsons(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    foo_package_snapshot = rule_runner.request(Snapshot, [PathGlobs(["src/js/foo/package.json"])])
    bar_package_snapshot = rule_runner.request(Snapshot, [PathGlobs(["src/js/bar/package.json"])])
    pkg_jsons = rule_runner.request(AllPackageJson, [])
    assert set(pkg_jsons) == {
        PackageJson(
            content=FrozenDict.deep_freeze(json.loads(given_package("ham", "0.0.1"))),
            name="ham",
            version="0.0.1",
            snapshot=foo_package_snapshot,
        ),
        PackageJson(
            content=FrozenDict.deep_freeze(json.loads(given_package("spam", "0.0.2"))),
            name="spam",
            version="0.0.2",
            snapshot=bar_package_snapshot,
        )
    }
