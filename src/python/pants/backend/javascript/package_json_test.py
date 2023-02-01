# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from typing import Iterable

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.package_json import (
    AllPackageJson,
    PackageJson,
    PackageJsonTarget,
    ReadPackageJsonRequest,
)
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *package_json.rules(),
            QueryRule(AllPackageJson, ()),
            QueryRule(Owners, (OwnersRequest,)),
            QueryRule(PackageJson, (ReadPackageJsonRequest,)),
        ],
        target_types=[PackageJsonTarget],
    )


def given_package(name: str, version: str) -> str:
    return json.dumps({"name": name, "version": version})


def given_package_with_workspaces(name: str, version: str, *workspaces: str) -> str:
    return json.dumps({"name": name, "version": version, "workspaces": list(workspaces)})


def get_snapshots_for_package(rule_runner: RuleRunner, *package_path: str) -> Iterable[Snapshot]:
    return (rule_runner.request(Snapshot, [PathGlobs([path])]) for path in package_path)


def test_parses_package_jsons(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    [foo_package_snapshot, bar_package_snapshot] = get_snapshots_for_package(
        rule_runner, "src/js/foo/package.json", "src/js/bar/package.json"
    )
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
        ),
    }


def test_parses_simple_workspace(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_workspaces("ham", "0.0.1", "bar"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    [root_package_snapshot, bar_package_snapshot] = get_snapshots_for_package(
        rule_runner, "src/js/package.json", "src/js/bar/package.json"
    )

    pkg_jsons = rule_runner.request(AllPackageJson, [])

    bar_package = PackageJson(
        content=FrozenDict.deep_freeze(json.loads(given_package("spam", "0.0.2"))),
        name="spam",
        version="0.0.2",
        snapshot=bar_package_snapshot,
    )
    assert set(pkg_jsons) == {
        PackageJson(
            content=FrozenDict.deep_freeze(
                json.loads(given_package_with_workspaces("ham", "0.0.1", "bar"))
            ),
            name="ham",
            version="0.0.1",
            snapshot=root_package_snapshot,
            workspaces=(bar_package,),
        ),
        bar_package,
    }


def test_ignores_self_reference_in_workspace(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_workspaces("ham", "0.0.1", "./"),
        }
    )
    [root_package_snapshot] = get_snapshots_for_package(rule_runner, "src/js/package.json")

    [pkg_json] = rule_runner.request(AllPackageJson, [])

    assert pkg_json == PackageJson(
        content=FrozenDict.deep_freeze(
            json.loads(given_package_with_workspaces("ham", "0.0.1", "./"))
        ),
        name="ham",
        version="0.0.1",
        snapshot=root_package_snapshot,
    )


def test_nested_workspaces(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_workspaces("ham", "0.0.1", "a"),
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": given_package_with_workspaces("spam", "0.0.1", "b"),
            "src/js/a/b/package.json": given_package(
                "egg",
                "0.0.1",
            ),
            "src/js/a/b/BUILD": "package_json()",
        }
    )
    pkg_jsons = rule_runner.request(AllPackageJson, [])

    [root_package_snapshot, a_package_snapshot, b_package_snapshot] = get_snapshots_for_package(
        rule_runner, "src/js/package.json", "src/js/a/package.json", "src/js/a/b/package.json"
    )
    b_package = PackageJson(
        content=FrozenDict.deep_freeze(json.loads(given_package("egg", "0.0.1"))),
        name="egg",
        version="0.0.1",
        snapshot=b_package_snapshot,
    )
    a_package = PackageJson(
        content=FrozenDict.deep_freeze(
            json.loads(given_package_with_workspaces("spam", "0.0.1", "b"))
        ),
        name="spam",
        version="0.0.1",
        snapshot=a_package_snapshot,
        workspaces=(b_package,),
    )
    assert set(pkg_jsons) == {
        PackageJson(
            content=FrozenDict.deep_freeze(
                json.loads(given_package_with_workspaces("ham", "0.0.1", "a"))
            ),
            name="ham",
            version="0.0.1",
            snapshot=root_package_snapshot,
            workspaces=(a_package,),
        ),
        a_package,
        b_package,
    }


def test_parses_simple_workspace_with_globbing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_workspaces("ham", "0.0.1", "./packages/*"),
            "src/js/packages/foo/BUILD": "package_json()",
            "src/js/packages/foo/package.json": given_package("egg", "2.0.0"),
            "src/js/packages/bar/BUILD": "package_json()",
            "src/js/packages/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    [root_package_snapshot, bar_package_snapshot, foo_package_snapshot] = get_snapshots_for_package(
        rule_runner,
        "src/js/package.json",
        "src/js/packages/bar/package.json",
        "src/js/packages/foo/package.json",
    )

    pkg_jsons = rule_runner.request(AllPackageJson, [])

    bar_package = PackageJson(
        content=FrozenDict.deep_freeze(json.loads(given_package("spam", "0.0.2"))),
        name="spam",
        version="0.0.2",
        snapshot=bar_package_snapshot,
    )
    foo_package = PackageJson(
        content=FrozenDict.deep_freeze(json.loads(given_package("egg", "2.0.0"))),
        name="egg",
        version="2.0.0",
        snapshot=foo_package_snapshot,
    )
    assert set(pkg_jsons) == {
        PackageJson(
            content=FrozenDict.deep_freeze(
                json.loads(given_package_with_workspaces("ham", "0.0.1", "./packages/*"))
            ),
            name="ham",
            version="0.0.1",
            snapshot=root_package_snapshot,
            workspaces=(bar_package, foo_package),
        ),
        foo_package,
        bar_package,
    }
