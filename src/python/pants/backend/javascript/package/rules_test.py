# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os.path
import tarfile
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
from pants.core.target_types import FilesGeneratorTarget
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest, Snapshot
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
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
            FilesGeneratorTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )


def test_creates_tar_for_package_json(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(dependencies=[":readme"])
                files(name="readme", sources=["*.md"])
                """
            ),
            "src/js/package.json": json.dumps(
                {"name": "ham", "version": "0.0.1", "browser": "lib/index.mjs"}
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
    tgt = rule_runner.get_target(Address("src/js", generated_name="ham"))
    result = rule_runner.request(BuiltPackage, [NodePackageTarFieldSet.create(tgt)])
    rule_runner.write_digest(result.digest)

    with tarfile.open(os.path.join(rule_runner.build_root, "ham-0.0.1.tgz")) as tar:
        assert {member.name for member in tar.getmembers()} == {
            "package/package.json",
            "package/lib/index.mjs",
            "package/README.md",
        }


def test_packages_files_as_resource(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """\
                package_json(
                    scripts=[
                        node_build_script(entry_point="build", outputs=["dist/index.cjs"])
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "browser": "lib/index.mjs",
                    "scripts": {"build": "echo 'blarb' >> dist/index.cjs"},
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
