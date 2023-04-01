# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
from typing import Iterable

import pytest

from pants.backend.javascript import nodejs_project, package_json
from pants.backend.javascript.nodejs_project import AllNodeJSProjects
from pants.backend.javascript.package_json import NodeThirdPartyPackageTarget, PackageJsonTarget
from pants.core.target_types import TargetGeneratorSourcesHelperTarget
from pants.engine.fs import PathGlobs
from pants.engine.internals.graph import Owners, OwnersRequest
from pants.engine.internals.native_engine import Snapshot
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *package_json.rules(),
            *nodejs_project.rules(),
            QueryRule(AllNodeJSProjects, ()),
            QueryRule(Owners, (OwnersRequest,)),
        ],
        target_types=[
            PackageJsonTarget,
            NodeThirdPartyPackageTarget,
            TargetGeneratorSourcesHelperTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )


def given_package(name: str, version: str) -> str:
    return json.dumps({"name": name, "version": version})


def given_package_with_workspaces(name: str, version: str, *workspaces: str) -> str:
    return json.dumps({"name": name, "version": version, "workspaces": list(workspaces)})


def get_snapshots_for_package(rule_runner: RuleRunner, *package_path: str) -> Iterable[Snapshot]:
    return (rule_runner.request(Snapshot, [PathGlobs([path])]) for path in package_path)


def test_parses_projects(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    projects = rule_runner.request(AllNodeJSProjects, [])
    assert {project.root_dir for project in projects} == {"src/js/foo", "src/js/bar"}


def test_parses_project_with_workspaces(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/package.json": given_package_with_workspaces("egg", "1.0.0", "foo", "bar"),
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    [project] = rule_runner.request(AllNodeJSProjects, [])
    assert project.root_dir == "src/js"
    assert {workspace.name for workspace in project.workspaces} == {"egg", "ham", "spam"}


def test_parses_project_with_nested_workspaces(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/package.json": given_package_with_workspaces("egg", "1.0.0", "foo"),
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package_with_workspaces("ham", "0.0.1", "bar"),
            "src/js/foo/bar/BUILD": "package_json()",
            "src/js/foo/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    [project] = rule_runner.request(AllNodeJSProjects, [])
    assert project.root_dir == "src/js"
    assert {workspace.name for workspace in project.workspaces} == {"egg", "ham", "spam"}


def test_workspaces_with_multiple_owners_is_an_error(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/package.json": given_package_with_workspaces("egg", "1.0.0", "foo/bar"),
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package_with_workspaces("ham", "0.0.1", "bar"),
            "src/js/foo/bar/BUILD": "package_json()",
            "src/js/foo/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    with pytest.raises(ExecutionError):
        rule_runner.request(AllNodeJSProjects, [])
