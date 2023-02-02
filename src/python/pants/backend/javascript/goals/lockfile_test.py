# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json

import pytest

from pants.backend.javascript.goals import lockfile
from pants.backend.javascript.goals.lockfile import (
    GeneratePackageLockJsonFile,
    KnownPackageJsonUserResolveNamesRequest,
)
from pants.backend.javascript.package_json import (
    AllPackageJson,
    PackageJsonForGlobs,
    PackageJsonTarget,
)
from pants.core.goals.generate_lockfiles import GenerateLockfileResult, KnownUserResolveNames
from pants.engine.fs import DigestContents, PathGlobs
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *lockfile.rules(),
            QueryRule(
                KnownUserResolveNames, (KnownPackageJsonUserResolveNamesRequest, AllPackageJson)
            ),
            QueryRule(AllPackageJson, ()),
            QueryRule(PackageJsonForGlobs, (PathGlobs,)),
            QueryRule(GenerateLockfileResult, (GeneratePackageLockJsonFile,)),
        ],
        target_types=[PackageJsonTarget],
    )


def given_package_with_name(name: str) -> str:
    return json.dumps({"name": name, "version": "0.0.1"})


def given_package_with_workspaces(name: str, version: str, *workspaces: str) -> str:
    return json.dumps({"name": name, "version": version, "workspaces": list(workspaces)})


def test_resolves_are_package_names(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/foo/BUILD": "package_json()",
            "src/js/foo/package.json": given_package_with_name("ham"),
            "src/js/bar/BUILD": "package_json()",
            "src/js/bar/package.json": given_package_with_name("spam"),
        }
    )
    pkg_jsons = rule_runner.request(AllPackageJson, [])
    resolves = rule_runner.request(
        KnownUserResolveNames, (pkg_jsons, KnownPackageJsonUserResolveNamesRequest())
    )
    assert set(resolves.names) == {"ham", "spam"}


def test_generates_lockfile_for_package_json(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_name("ham"),
        }
    )
    [pkg_json] = rule_runner.request(PackageJsonForGlobs, [PathGlobs(["src/js/package.json"])])

    lockfile = rule_runner.request(
        GenerateLockfileResult,
        (
            GeneratePackageLockJsonFile(
                resolve_name="ham",
                lockfile_dest="src/js/package-lock.json",
                pkg_json=pkg_json,
                diff=False,
            ),
        ),
    )

    digest_contents = rule_runner.request(DigestContents, [lockfile.digest])

    assert json.loads(digest_contents[0].content) == {
        "name": "ham",
        "version": "0.0.1",
        "lockfileVersion": 2,
        "requires": True,
        "packages": {"": {"name": "ham", "version": "0.0.1"}},
    }


def test_generates_lockfile_for_package_json_workspace(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": given_package_with_workspaces("ham", "1.0.0", "a"),
            "src/js/a/BUILD": "package_json()",
            "src/js/a/package.json": given_package_with_workspaces("spam", "0.1.0"),
        }
    )
    [pkg_json] = rule_runner.request(PackageJsonForGlobs, [PathGlobs(["src/js/package.json"])])

    lockfile = rule_runner.request(
        GenerateLockfileResult,
        (
            GeneratePackageLockJsonFile(
                resolve_name="ham",
                lockfile_dest="src/js/package-lock.json",
                pkg_json=pkg_json,
                diff=False,
            ),
        ),
    )

    digest_contents = rule_runner.request(DigestContents, [lockfile.digest])

    assert json.loads(digest_contents[0].content) == {
        "name": "ham",
        "version": "1.0.0",
        "lockfileVersion": 2,
        "requires": True,
        "dependencies": {"spam": {"version": "file:a"}},
        "packages": {
            "": {"name": "ham", "version": "1.0.0", "workspaces": ["a"]},
            "a": {"name": "spam", "version": "0.1.0"},
            "node_modules/spam": {"link": True, "resolved": "a"},
        },
    }
