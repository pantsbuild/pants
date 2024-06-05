# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os.path
import tarfile
import textwrap
from textwrap import dedent
from typing import cast

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.package.rules import (
    GenerateResourcesFromNodeBuildScriptRequest,
    NodePackageTarFieldSet,
)
from pants.backend.javascript.package.rules import rules as package_rules
from pants.backend.javascript.package_json import NPMDistributionTarget
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, Snapshot
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture(params=[("pnpm", "9.1.4"), ("npm", "10.8.1"), ("yarn", "1.22.22")])
def package_manager_and_version(request) -> tuple[str, str]:
    return request.param


@pytest.fixture
def rule_runner(package_manager_and_version: tuple[str, str]) -> RuleRunner:
    package_manager, package_manager_version = package_manager_and_version
    rule_runner = RuleRunner(
        rules=[
            *package_rules(),
            QueryRule(BuiltPackage, (NodePackageTarFieldSet,)),
            QueryRule(GeneratedSources, (GenerateResourcesFromNodeBuildScriptRequest,)),
            QueryRule(Snapshot, (Digest,)),
        ],
        target_types=[
            *package_json.target_types(),
            JSSourceTarget,
            JSSourcesGeneratorTarget,
            NPMDistributionTarget,
            FilesGeneratorTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )
    rule_runner.set_options([f"--nodejs-package-manager={package_manager}@{package_manager_version}"], env_inherit={"PATH"})
    return rule_runner


def test_creates_tar_for_package_json(rule_runner: RuleRunner, package_manager_and_version: tuple[str, str]) -> None:
    package_manager, package_manager_version = package_manager_and_version
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(dependencies=[":readme"])
                files(name="readme", sources=["*.md"])

                npm_distribution(name="ham-dist")
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "browser": "lib/index.mjs",
                    "packageManager": f"{package_manager}@{package_manager_version}",
                }
            ),
            "src/js/README.md": "",
            "src/js/package-lock.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "lockfileVersion": 2,
                    "requires": True,
                    "packages": {"": {"name": "ham", "version": "0.0.1"}},
                }
            ),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    tgt = rule_runner.get_target(Address("src/js", target_name="ham-dist"))
    result = rule_runner.request(BuiltPackage, [NodePackageTarFieldSet.create(tgt)])
    rule_runner.write_digest(result.digest)

    archive_name = "ham-v0.0.1.tgz" if package_manager == "yarn" else "ham-0.0.1.tgz"
    with tarfile.open(os.path.join(rule_runner.build_root, archive_name)) as tar:
        assert {member.name for member in tar.getmembers()}.issuperset(
            {
                "package/package.json",
                "package/lib/index.mjs",
                "package/README.md",
            }
        )


def test_packages_files_as_resource(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", output_files=["dist/index.cjs"])
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "browser": "lib/index.mjs",
                    "scripts": {"build": "mkdir dist && echo 'blarb' >> dist/index.cjs"},
                }
            ),
            "src/js/package-lock.json": json.dumps({}),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    tgt = rule_runner.get_target(Address("src/js", generated_name="build"))
    snapshot = rule_runner.request(Snapshot, (EMPTY_DIGEST,))
    result = rule_runner.request(
        GeneratedSources, [GenerateResourcesFromNodeBuildScriptRequest(snapshot, tgt)]
    )
    rule_runner.write_digest(result.snapshot.digest)
    with open(os.path.join(rule_runner.build_root, "src/js/dist/index.cjs")) as f:
        assert f.read() == "blarb\n"


@pytest.fixture
def workspace_files(package_manager_and_version: tuple[str, str]) -> dict[str, str]:
    package_manager, _ = package_manager_and_version
    if package_manager == "npm":
        return {
            "src/js/package-lock.json": json.dumps(
                {
                    "name": "spam",
                    "version": "0.0.1",
                    "lockfileVersion": 2,
                    "requires": True,
                    "dependencies": {"ham": {"version": "file:a"}},
                    "packages": {
                        "": {"name": "spam", "version": "0.0.1", "workspaces": ["a"]},
                        "a": {"name": "ham", "version": "0.0.1"},
                        "node_modules/ham": {"link": True, "resolved": "a"},
                    },
                }
            )
        }
    if package_manager == "pnpm":
        return {
            "src/js/pnpm-workspace.yaml": textwrap.dedent(
                """\
                packages:
                """
            ),
            "src/js/pnpm-lock.yaml": json.dumps(
                {
                    "importers": {
                        ".": {"specifiers": {}},
                        "a": {"specifiers": {}},
                    },
                    "lockfileVersion": 5.3,
                }
            ),
        }
    if package_manager == "yarn":
        return {
            "src/js/yarn.lock": textwrap.dedent(
                """\
                # THIS IS AN AUTOGENERATED FILE. DO NOT EDIT THIS FILE DIRECTLY.
                # yarn lockfile v1


                """
            )
        }
    raise AssertionError(f"No lockfile implemented for {package_manager}.")


def test_packages_files_as_resource_in_workspace(
    rule_runner: RuleRunner, package_manager_and_version: tuple[str, str], workspace_files: dict[str, str]
) -> None:
    package_manager, package_manager_version = package_manager_and_version
    rule_runner.write_files(
        {
            **workspace_files,
            "src/js/package.json": json.dumps(
                {
                    "name": "spam",
                    "version": "0.0.1",
                    "packageManager": f"{package_manager}@{package_manager_version}",
                    "workspaces": ["a"],
                    "private": True
                }
            ),
            "src/js/BUILD": "package_json()",
            "src/js/a/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", output_files=["dist/index.cjs"])
                    ]
                )
                """
            ),
            "src/js/a/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "packageManager": f"{package_manager}@{package_manager_version}",
                    "browser": "lib/index.mjs",
                    "scripts": {"build": "mkdir dist && echo 'blarb' >> dist/index.cjs"},
                }
            ),
            "src/js/a/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/a/lib/index.mjs": "",
        }
    )
    tgt = rule_runner.get_target(Address("src/js/a", generated_name="build"))
    snapshot = rule_runner.request(Snapshot, (EMPTY_DIGEST,))
    result = rule_runner.request(
        GeneratedSources, [GenerateResourcesFromNodeBuildScriptRequest(snapshot, tgt)]
    )
    rule_runner.write_digest(result.snapshot.digest)
    with open(os.path.join(rule_runner.build_root, "src/js/a/dist/index.cjs")) as f:
        assert f.read() == "blarb\n"


def test_extra_envs(rule_runner: RuleRunner, package_manager_and_version: tuple[str, str]) -> None:
    package_manager, package_manager_version = package_manager_and_version
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", extra_env_vars=["FOO=BAR"], output_files=["dist/index.cjs"])
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "browser": "lib/index.mjs",
                    "packageManager": f"{package_manager}@{package_manager_version}",
                    "scripts": {"build": "mkdir dist && echo $FOO >> dist/index.cjs"},
                }
            ),
            "src/js/package-lock.json": json.dumps({}),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources()
                """
            ),
            "src/js/lib/index.mjs": "",
        }
    )
    tgt = rule_runner.get_target(Address("src/js", generated_name="build"))
    snapshot = rule_runner.request(Snapshot, (EMPTY_DIGEST,))
    result = rule_runner.request(
        GeneratedSources, [GenerateResourcesFromNodeBuildScriptRequest(snapshot, tgt)]
    )
    rule_runner.write_digest(result.snapshot.digest)
    with open(os.path.join(rule_runner.build_root, "src/js/dist/index.cjs")) as f:
        assert f.read() == "BAR\n"
