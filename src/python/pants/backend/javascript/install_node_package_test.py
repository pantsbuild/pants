# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
from textwrap import dedent

import pytest

from pants.backend.javascript import install_node_package, package_json
from pants.backend.javascript.install_node_package import (
    InstalledNodePackage,
    InstalledNodePackageRequest,
)
from pants.backend.javascript.package_json import PackageJsonTarget
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
from pants.build_graph.address import Address
from pants.engine.fs import DigestContents
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *install_node_package.rules(),
            *package_json.rules(),
            QueryRule(InstalledNodePackage, (InstalledNodePackageRequest,)),
        ],
        target_types=[PackageJsonTarget, JSSourcesGeneratorTarget],
        objects=dict(package_json.build_file_aliases().objects),
    )


def test_install_node_package_with_extra_env_vars(rule_runner: RuleRunner) -> None:
    # Test both subsystem and target-level environment variables
    rule_runner.set_options(
        [
            "--nodejs-package-manager-extra-env-vars=['GLOBAL_VAR=global_value']",
            "--nodejs-tools=['env']",
        ],
        env_inherit={"PATH"},
    )

    rule_runner.write_files(
        {
            "src/js/BUILD": dedent(
                """
                package_json(
                    extra_env_vars=[
                        "TARGET_VAR=target_value",
                    ]
                )
                """
            ),
            "src/js/package.json": json.dumps(
                {
                    "name": "test-package",
                    "version": "1.0.0",
                    "packageManager": "yarn@1.22.22",
                    "scripts": {
                        "postinstall": "env > node_modules/env-vars.txt",
                    },
                }
            ),
        }
    )

    installed_package = rule_runner.request(
        InstalledNodePackage,
        [InstalledNodePackageRequest(Address("src/js"))],
    )
    digest = rule_runner.request(DigestContents, [installed_package.digest])
    env_vars_file = next((f for f in digest if f.path == "src/js/node_modules/env-vars.txt"), None)
    assert env_vars_file is not None

    content = env_vars_file.content.decode("utf-8")
    actual_env_vars = {}
    for line in content.split("\n"):
        if "=" in line:
            key, value = line.split("=", 1)
            actual_env_vars[key] = value

    assert "TARGET_VAR" in actual_env_vars
    assert actual_env_vars["TARGET_VAR"] == "target_value"

    assert "GLOBAL_VAR" in actual_env_vars
    assert actual_env_vars["GLOBAL_VAR"] == "global_value"
