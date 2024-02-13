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
from pants.testutil.rule_runner import RuleRunner, engine_error


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


def given_package(name: str, version: str, package_manager: str | None = None) -> str:
    return json.dumps({"name": name, "version": version, "packageManager": package_manager})


def given_package_with_workspaces(
    name: str, version: str, *workspaces: str, package_manager: str | None = None
) -> str:
    return json.dumps(
        {
            "name": name,
            "version": version,
            "packageManager": package_manager,
            "workspaces": list(workspaces),
        }
    )


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


def test_immutable_install_args_property(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("foo", "0.0.1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("bar", "0.0.2", package_manager="yarn@1.22.19"),
            "src/js/baz/BUILD": "package_json()",
            "src/js/baz/package.json": given_package("baz", "0.0.3", package_manager="yarn@2.4.3"),
            "src/js/qux/BUILD": "package_json()",
            "src/js/qux/package.json": given_package("qux", "0.0.4", package_manager="pnpm@7.5.0"),
        }
    )
    projects = rule_runner.request(AllNodeJSProjects, [])
    assert {project.immutable_install_args for project in projects} == {
        ("clean-install",),
        ("install", "--frozen-lockfile"),
        ("install", "--immutable"),
        ("install", "--frozen-lockfile"),
    }


def test_root_package_json_is_supported(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "package_json()",
            "package.json": given_package("ham", "0.0.1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    projects = rule_runner.request(AllNodeJSProjects, [])
    assert {project.root_dir for project in projects} == {"", "src/js/bar"}
    assert {project.default_resolve_name for project in projects} == {"nodejs-default", "js.bar"}


def test_parses_project_with_workspaces(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/package.json": given_package_with_workspaces("egg", "1.0.0", "foo", "bar"),
            "src/js/BUILD": "package_json()",
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    [project] = rule_runner.request(AllNodeJSProjects, [])
    assert project.root_dir == "src/js"
    assert {workspace.name for workspace in project.workspaces} == {"egg", "ham", "spam"}
    assert project.package_manager == "npm"


def test_parses_project_with_nested_workspaces(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/package.json": given_package_with_workspaces("egg", "1.0.0", "foo"),
            "src/js/BUILD": "package_json()",
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
            "src/js/BUILD": "package_json()",
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package_with_workspaces("ham", "0.0.1", "bar"),
            "src/js/foo/bar/BUILD": "package_json()",
            "src/js/foo/bar/package.json": given_package("spam", "0.0.2"),
        }
    )
    with pytest.raises(ExecutionError):
        rule_runner.request(AllNodeJSProjects, [])


def test_workspaces_with_default_conflicting_package_manager_versions_is_an_error(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.set_options(
        ["--nodejs-package-manager=npm", "--nodejs-package-managers={'npm': '1'}"]
    )
    rule_runner.write_files(
        {
            "src/js/package.json": given_package_with_workspaces("egg", "1.0.0", "foo", "bar"),
            "src/js/BUILD": "package_json()",
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1", package_manager="npm@1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2", package_manager="npm@2"),
        }
    )
    expected_error = "Workspace spam@0.0.2's package manager npm@2 is not compatible"
    with engine_error(ValueError, contains=expected_error):
        rule_runner.request(AllNodeJSProjects, [])


def test_mixing_default_version_and_workspace_version_is_an_error(rule_runner: RuleRunner) -> None:
    """Not allowed because Corepack will only inspect the top-level package.json.

    This will result in the default version being used, even when running commands targeting `ham`.
    """
    rule_runner.set_options(["--nodejs-package-manager=npm", "--nodejs-package-managers={}"])
    rule_runner.write_files(
        {
            "src/js/package.json": given_package_with_workspaces("egg", "1.0.0", "foo", "bar"),
            "src/js/BUILD": "package_json()",
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1", package_manager="npm@1"),
        }
    )
    expected_error = "Workspace ham@0.0.1's package manager npm@1 is not compatible"
    with engine_error(ValueError, contains=expected_error):
        rule_runner.request(AllNodeJSProjects, [])


def test_workspaces_with_package_json_conflicting_package_manager_versions_is_an_error(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.set_options(["--nodejs-package-manager=", "--nodejs-package-managers={}"])
    rule_runner.write_files(
        {
            "src/js/package.json": given_package_with_workspaces(
                "egg", "1.0.0", "foo", "bar", package_manager="npm@2"
            ),
            "src/js/BUILD": "package_json()",
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1", package_manager="npm@1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2", package_manager="npm@2"),
        }
    )
    expected_error = "Workspace ham@0.0.1's package manager npm@1 is not compatible"
    with engine_error(ValueError, contains=expected_error):
        rule_runner.request(AllNodeJSProjects, [])


def test_workspaces_without_conflicting_package_manager_versions_works(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/js/package.json": given_package_with_workspaces(
                "egg", "1.0.0", "foo", "bar", package_manager="npm@1"
            ),
            "src/js/BUILD": "package_json()",
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package("ham", "0.0.1", package_manager="npm@1"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package("spam", "0.0.2", package_manager="npm@1"),
        }
    )

    assert len(rule_runner.request(AllNodeJSProjects, [])) == 1
