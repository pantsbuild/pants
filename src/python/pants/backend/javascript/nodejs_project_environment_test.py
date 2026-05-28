# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json

import pytest

from pants.backend.javascript import nodejs_project_environment, package_json
from pants.backend.javascript.nodejs_project import AllNodeJSProjects, NodeJSProject
from pants.backend.javascript.nodejs_project_environment import (
    NodeJsProjectEnvironment,
    NodeJSProjectEnvironmentRequest,
)
from pants.backend.javascript.package_json import PackageJsonTarget
from pants.build_graph.address import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *nodejs_project_environment.rules(),
            QueryRule(AllNodeJSProjects, ()),
            QueryRule(NodeJsProjectEnvironment, (NodeJSProjectEnvironmentRequest,)),
        ],
        target_types=[PackageJsonTarget],
        objects=dict(package_json.build_file_aliases().objects),
    )


def _request_project(rule_runner: RuleRunner) -> NodeJSProject:
    [project] = rule_runner.request(AllNodeJSProjects, [])
    return project


def test_node_modules_directories_single_workspace(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": json.dumps({"name": "ham", "version": "0.0.1"}),
        }
    )
    project = _request_project(rule_runner)
    env = rule_runner.request(
        NodeJsProjectEnvironment,
        [NodeJSProjectEnvironmentRequest(Address("src/js", generated_name="ham"))],
    )

    assert project.single_workspace
    assert tuple(env.node_modules_directories) == ("node_modules",)


@pytest.mark.parametrize("package_manager", ["npm", "yarn"])
def test_node_modules_directories_yields_all_member_paths_for_workspace(
    rule_runner: RuleRunner, package_manager: str
) -> None:
    """Yield root + every member's node_modules, regardless of package manager.

    The path-generation code is the same for npm/yarn/pnpm; the tsc test in
    check_test.py exercises the pnpm install pipeline end-to-end.
    """
    rule_runner.set_options([f"--nodejs-package-manager={package_manager}"])
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": json.dumps(
                {
                    "name": "egg",
                    "version": "1.0.0",
                    "private": True,
                    "workspaces": ["foo", "bar"],
                }
            ),
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": json.dumps({"name": "ham", "version": "0.0.1"}),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": json.dumps({"name": "spam", "version": "0.0.2"}),
        }
    )
    env = rule_runner.request(
        NodeJsProjectEnvironment,
        [NodeJSProjectEnvironmentRequest(Address("src/js/foo", generated_name="ham"))],
    )

    assert not env.project.single_workspace
    assert env.package is not None
    assert set(env.node_modules_directories) == {
        "node_modules",
        "foo/node_modules",
        "bar/node_modules",
    }


def test_node_modules_directories_from_root_yields_only_root(rule_runner: RuleRunner) -> None:
    """from_root() envs (lockfile generation) yield only the root's node_modules.

    Lockfile generation runs against the project as a whole, not a specific member,
    so member node_modules paths aren't relevant and shouldn't leak in.
    """
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": json.dumps(
                {
                    "name": "egg",
                    "version": "1.0.0",
                    "private": True,
                    "workspaces": ["foo", "bar"],
                }
            ),
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": json.dumps({"name": "ham", "version": "0.0.1"}),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": json.dumps({"name": "spam", "version": "0.0.2"}),
        }
    )
    project = _request_project(rule_runner)
    env = NodeJsProjectEnvironment.from_root(project)

    assert not project.single_workspace
    assert env.package is None
    assert tuple(env.node_modules_directories) == ("node_modules",)


def test_node_modules_directories_nested_workspaces(rule_runner: RuleRunner) -> None:
    """Nested workspace layouts emit relative paths from the project root."""
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": json.dumps(
                {
                    "name": "egg",
                    "version": "1.0.0",
                    "private": True,
                    "workspaces": ["foo"],
                }
            ),
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "private": True,
                    "workspaces": ["bar"],
                }
            ),
            "src/js/foo/bar/BUILD": "package_json()",
            "src/js/foo/bar/package.json": json.dumps({"name": "spam", "version": "0.0.2"}),
        }
    )
    env = rule_runner.request(
        NodeJsProjectEnvironment,
        [NodeJSProjectEnvironmentRequest(Address("src/js/foo/bar", generated_name="spam"))],
    )

    assert set(env.node_modules_directories) == {
        "node_modules",
        "foo/node_modules",
        "foo/bar/node_modules",
    }
