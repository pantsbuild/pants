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
    NodePackageTarFieldSet,
)
from pants.backend.javascript.package.rules import rules as package_rules
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FileTarget, ResourceTarget
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, Snapshot
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
            QueryRule(Snapshot, (Digest,)),
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


@pytest.mark.parametrize(
    "lockfile, package_manager",
    [
        pytest.param(Path(__file__).parent / "package-lock.json", "npm"),
        pytest.param(Path(__file__).parent / "pnpm-lock.yaml", "pnpm"),
    ],
)
def test_packages_sources_as_resource_using_build_tool(
    rule_runner: RuleRunner, package_manager: str, lockfile: Path
) -> None:
    rule_runner.set_options([f"--nodejs-package-manager={package_manager}"], env_inherit={"PATH"})
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(
                            entry_point="build",
                            output_directories=["dist"],
                            extra_caches=[".parcel-cache"],
                        )
                    ],
                    dependencies=[":npmrc"],
                )
                file(name="npmrc", source=".npmrc")
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "source": "lib/index.mjs",
                    "scripts": {
                        "build": "parcel build lib/index.mjs --dist-dir=dist --cache-dir=.parcel-cache"
                    },
                    "devDependencies": {"parcel": "2.6.2"},
                }
            ),
            "src/js/.npmrc": "strict-peer-dependencies=false",
            f"src/js/{lockfile.name}": lockfile.read_text(),
            "src/js/lib/BUILD": dedent(
                """\
                javascript_sources(dependencies=[":style"])
                resource(name="style", source="style.css")
                """
            ),
            "src/js/lib/style.css": "",
            "src/js/lib/index.mjs": "import './style.css' ",
        }
    )
    tgt = rule_runner.get_target(Address("src/js", generated_name="build"))
    snapshot = rule_runner.request(Snapshot, (EMPTY_DIGEST,))
    result = rule_runner.request(
        GeneratedSources, [GenerateResourcesFromNodeBuildScriptRequest(snapshot, tgt)]
    )
    assert result.snapshot.files == (
        "src/js/dist/index.css",
        "src/js/dist/index.css.map",
        "src/js/dist/index.js",
        "src/js/dist/index.js.map",
    )
