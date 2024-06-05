# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import textwrap

import pytest
import yaml

from pants.backend.javascript.goals import lockfile
from pants.backend.javascript.goals.lockfile import (
    GeneratePackageLockJsonFile,
    KnownPackageJsonUserResolveNamesRequest,
    RequestedPackageJsonUserResolveNames,
)
from pants.backend.javascript.nodejs_project import AllNodeJSProjects
from pants.backend.javascript.package_json import (
    AllPackageJson,
    PackageJsonForGlobs,
    PackageJsonTarget,
)
from pants.backend.javascript.subsystems.nodejs import UserChosenNodeJSResolveAliases
from pants.core.goals.generate_lockfiles import (
    GenerateLockfileResult,
    KnownUserResolveNames,
    UserGenerateLockfiles,
)
from pants.core.target_types import FileTarget
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *lockfile.rules(),
            QueryRule(
                KnownUserResolveNames, (KnownPackageJsonUserResolveNamesRequest, AllNodeJSProjects)
            ),
            QueryRule(AllNodeJSProjects, ()),
            QueryRule(PackageJsonForGlobs, (PathGlobs,)),
            QueryRule(AllPackageJson, (PathGlobs,)),
            QueryRule(GenerateLockfileResult, (GeneratePackageLockJsonFile,)),
            QueryRule(
                UserGenerateLockfiles,
                (
                    RequestedPackageJsonUserResolveNames,
                    AllNodeJSProjects,
                    UserChosenNodeJSResolveAliases,
                ),
            ),
        ],
        target_types=[PackageJsonTarget, FileTarget],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def given_package_with_name(name: str) -> str:
    return json.dumps({"name": name, "version": "0.0.1"})


def given_package_with_package_manager_and_workspaces(
    name: str, version: str, package_manager: str, dependencies: dict[str, str] | None = None, *workspaces: str
) -> str:
    return json.dumps(
        {
            "name": name,
            "version": version,
            "private": True,
            "packageManager": package_manager,
            "dependencies": dependencies or {},
            "workspaces": list(workspaces),
        }
    )


def test_resolves_are_dotted_package_paths(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package_with_name("ham"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package_with_name("spam"),
        }
    )
    projects = rule_runner.request(AllNodeJSProjects, [])
    resolves = rule_runner.request(
        KnownUserResolveNames, (projects, KnownPackageJsonUserResolveNamesRequest())
    )
    assert set(resolves.names) == {"js.foo", "js.bar"}


def test_user_can_override_resolve_aliases(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package_with_name("ham"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package_with_name("spam"),
        }
    )
    projects = rule_runner.request(AllNodeJSProjects, [])
    rule_runner.set_options(["--nodejs-resolves={'user:1': 'src/js/foo/package-lock.json'}"])
    resolves = rule_runner.request(
        KnownUserResolveNames, (projects, KnownPackageJsonUserResolveNamesRequest())
    )
    assert set(resolves.names) == {"user:1", "js.bar"}


def test_user_override_non_existing_resolve_is_an_error(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package_with_name("ham"),
        }
    )
    projects = rule_runner.request(AllNodeJSProjects, [])
    rule_runner.set_options(["--nodejs-resolves={'user:1': 'does/not/exist/package-lock.json'}"])
    with pytest.raises(ExecutionError):
        rule_runner.request(
            KnownUserResolveNames, (projects, KnownPackageJsonUserResolveNamesRequest())
        )


@pytest.mark.parametrize(
    "alias_args, expected_resolve",
    [
        pytest.param(
            ["--nodejs-resolves={'my-resolve': 'src/js/package-lock.json'}"],
            "my-resolve",
            id="Aliased resolve",
        ),
        pytest.param([""], "js", id="Default resolve"),
    ],
)
def test_generates_lockfile_with_expected_resolve_name(
    rule_runner: RuleRunner, alias_args: list[str], expected_resolve: str
) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_name("ham"),
        }
    )
    projects = rule_runner.request(AllNodeJSProjects, [])
    rule_runner.set_options(alias_args)
    [lockfile] = rule_runner.request(
        UserGenerateLockfiles,
        (
            projects,
            RequestedPackageJsonUserResolveNames((expected_resolve,)),
            UserChosenNodeJSResolveAliases(),
        ),
    )
    assert lockfile.resolve_name == expected_resolve


def test_generates_lockfile_for_package_json_project(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_name("ham"),
        }
    )
    [project] = rule_runner.request(AllNodeJSProjects, [])

    lockfile = rule_runner.request(
        GenerateLockfileResult,
        (
            GeneratePackageLockJsonFile(
                resolve_name="js",
                lockfile_dest="src/js/package-lock.json",
                project=project,
                diff=False,
            ),
        ),
    )

    digest_contents = rule_runner.request(DigestContents, [lockfile.digest])

    assert json.loads(digest_contents[0].content) == {
        "name": "ham",
        "version": "0.0.1",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {"": {"name": "ham", "version": "0.0.1"}},
    }


def test_generates_lockfile_for_npm_package_json_workspace(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_package_manager_and_workspaces("ham", "1.0.0", "npm@10.7.0", None, "a"),
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": given_package_with_package_manager_and_workspaces("spam", "0.1.0", "npm@10.7.0"),
        }
    )
    [project] = rule_runner.request(AllNodeJSProjects, [])

    lockfile = rule_runner.request(
        GenerateLockfileResult,
        (
            GeneratePackageLockJsonFile(
                resolve_name="js",
                lockfile_dest="src/js/package-lock.json",
                project=project,
                diff=False,
            ),
        ),
    )

    digest_contents = rule_runner.request(DigestContents, [lockfile.digest])

    assert json.loads(digest_contents[0].content) == {
        "name": "ham",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "dependencies": {"spam": {"version": "file:a"}},
        "packages": {
            "": {"name": "ham", "version": "1.0.0", "workspaces": ["a"]},
            "a": {"name": "spam", "version": "0.1.0"},
            "node_modules/spam": {"link": True, "resolved": "a"},
        },
    }


def test_generates_lockfile_for_pnpm_package_json_workspace(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--nodejs-package-manager=pnpm"], env_inherit={"PATH"})
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/pnpm-workspace.yaml": "",
            "src/js/package.json": given_package_with_package_manager_and_workspaces(
                "ham", "1.0.0", "pnpm@9.1.4", {"spam": "workspace:*"}
            ),
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": given_package_with_package_manager_and_workspaces("spam", "0.1.0", "pnpm@9.1.4"),
        }
    )
    [project] = rule_runner.request(AllNodeJSProjects, [])

    lockfile = rule_runner.request(
        GenerateLockfileResult,
        (
            GeneratePackageLockJsonFile(
                resolve_name="js",
                lockfile_dest="src/js/pnpm-lock.yaml",
                project=project,
                diff=False,
            ),
        ),
    )

    digest_contents = rule_runner.request(DigestContents, [lockfile.digest])

    assert yaml.safe_load(digest_contents[0].content) == {
        "importers": {
            ".": {"dependencies": {"spam": {"specifier": "workspace:*", "version": "link:a"}}},
            "a": {},
        },
        "lockfileVersion": '9.0',
        'settings': {
             'autoInstallPeers': True,
             'excludeLinksFromLockfile': False,
        }
    }


def test_generates_lockfile_for_yarn_package_json_workspace(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(["--nodejs-package-manager=yarn"], env_inherit={"PATH"})
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_package_manager_and_workspaces(
                "ham", "1.0.0", "yarn@4.2.2", {"spam": "*"}, "a"
            ),
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": given_package_with_package_manager_and_workspaces("spam", "0.1.0", "yarn@4.2.2"),
        }
    )
    [project] = rule_runner.request(AllNodeJSProjects, [])

    lockfile = rule_runner.request(
        GenerateLockfileResult,
        (
            GeneratePackageLockJsonFile(
                resolve_name="js",
                lockfile_dest="src/js/yarn.lock",
                project=project,
                diff=False,
            ),
        ),
    )

    digest_contents = rule_runner.request(DigestContents, [lockfile.digest])

    assert (
        digest_contents[0].content.decode().strip()
        == textwrap.dedent(
            """\
        # THIS IS AN AUTOGENERATED FILE. DO NOT EDIT THIS FILE DIRECTLY.
        # yarn lockfile v1
        """
        ).strip()
    )
