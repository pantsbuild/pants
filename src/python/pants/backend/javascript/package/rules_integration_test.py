# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.package.rules import (
    GenerateResourcesFromNodeBuildScriptRequest,
    NodeBuildScriptPackageFieldSet,
    NodePackageTarFieldSet,
)
from pants.backend.javascript.package.rules import rules as package_rules
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FileTarget, ResourceTarget
from pants.engine.fs import DigestEntries
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, RemovePrefix, Snapshot
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *package_rules(),
            QueryRule(BuiltPackage, (NodePackageTarFieldSet,)),
            QueryRule(GeneratedSources, (GenerateResourcesFromNodeBuildScriptRequest,)),
            QueryRule(BuiltPackage, (NodeBuildScriptPackageFieldSet,)),
            QueryRule(Snapshot, (Digest,)),
            QueryRule(DigestEntries, (Digest,)),
        ],
        target_types=[
            *package_json.target_types(),
            JSSourceTarget,
            JSSourcesGeneratorTarget,
            ResourceTarget,
            FileTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


@pytest.fixture(
    params=[
        pytest.param((Path(__file__).parent / "package-lock.json", "npm"), id="npm"),
        pytest.param((Path(__file__).parent / "pnpm-lock.yaml", "pnpm"), id="pnpm"),
        pytest.param((Path(__file__).parent / "yarn.lock", "yarn"), id="yarn"),
    ],
    autouse=True,
)
def configure_runner_with_js_project(request, rule_runner: RuleRunner) -> RuleRunner:
    lockfile, package_manager = request.param
    rule_runner.set_options(
        [f"--nodejs-package-manager={package_manager}"],
        env_inherit={"PATH"},
    )
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    dependencies=[":npmrc"],
                )
                file(name="npmrc", source=".npmrc")
                """
            ),
            "src/js/.npmrc": "strict-peer-dependencies=false",
            f"src/js/{lockfile.name}": lockfile.read_text(),
            "src/js/package.json": json.dumps(
                {
                    "name": "root",
                    "version": "0.0.1",
                    "workspaces": ["ham", "child-lib"],
                    "private": True,
                }
            ),
            "src/js/pnpm-workspace.yaml": dedent(
                """\
                packages:
                - "./ham"
                - "./child-lib"
                """
            ),
            "src/js/ham/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(
                            entry_point="build",
                            output_directories=["dist"],
                            extra_caches=[".parcel-cache"],
                        )
                    ],
                )
                javascript_sources(name="hamjs", dependencies=[":style"])
                resource(name="style", source="style.css")
                """
            ),
            "src/js/.npmrc": "strict-peer-dependencies=false",
            f"src/js/{lockfile.name}": lockfile.read_text(),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources(name="hamjs", dependencies=[":style"])
                resource(name="style", source="style.css")
                """
            ),
            "src/js/ham/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "source": "index.mjs",
                    "scripts": {
                        "build": "parcel build index.mjs --dist-dir=dist --cache-dir=.parcel-cache"
                    },
                    "dependencies": {"child-lib": "*"},
                    "devDependencies": {"parcel": "^2.12.0"},
                    "private": True,
                }
            ),
            "src/js/ham/style.css": "",
            "src/js/ham/index.mjs": "import './style.css'; import * as cl from 'child-lib';",
            "src/js/child-lib/BUILD": dedent(
                """\
                javascript_sources(name="js")
                package_json()
                """
            ),
            "src/js/child-lib/index.mjs": "console.log('child-lib')",
            "src/js/child-lib/package.json": json.dumps(
                {"name": "child-lib", "version": "0.0.1", "source": "index.mjs"}
            ),
        }
    )
    return rule_runner


def test_packages_sources_as_resource_using_build_tool(rule_runner: RuleRunner) -> None:
    tgt = rule_runner.get_target(Address("src/js/ham", generated_name="build"))
    snapshot = rule_runner.request(Snapshot, (EMPTY_DIGEST,))

    result = rule_runner.request(
        GeneratedSources, [GenerateResourcesFromNodeBuildScriptRequest(snapshot, tgt)]
    )
    assert result.snapshot.files == (
        "src/js/ham/dist/index.css",
        "src/js/ham/dist/index.css.map",
        "src/js/ham/dist/index.js",
        "src/js/ham/dist/index.js.map",
    )


def test_packages_sources_as_package_using_build_tool(rule_runner: RuleRunner) -> None:
    tgt = rule_runner.get_target(Address("src/js/ham", generated_name="build"))
    result = rule_runner.request(BuiltPackage, [NodeBuildScriptPackageFieldSet.create(tgt)])

    output_digest = rule_runner.request(Digest, [RemovePrefix(result.digest, "src.js.ham/build")])
    entries = rule_runner.request(DigestEntries, [output_digest])

    assert result.artifacts[0].relpath == "dist"

    assert sorted(entry.path for entry in entries) == [
        "ham/dist/index.css",
        "ham/dist/index.css.map",
        "ham/dist/index.js",
        "ham/dist/index.js.map",
    ]
