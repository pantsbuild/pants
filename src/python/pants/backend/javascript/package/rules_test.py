# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import os.path
import tarfile
from textwrap import dedent

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.package.rules import NodePackageTarFieldSet
from pants.backend.javascript.package.rules import rules as package_rules
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget, JSSourceTarget
from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage
from pants.core.target_types import FilesGeneratorTarget
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *package_rules(),
            QueryRule(BuiltPackage, (NodePackageTarFieldSet,)),
        ],
        target_types=[
            *package_json.target_types(),
            JSSourceTarget,
            JSSourcesGeneratorTarget,
            FilesGeneratorTarget,
        ],
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
