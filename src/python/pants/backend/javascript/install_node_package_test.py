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
    InstalledNodePackageWithSource,
)
from pants.backend.javascript.nodejs_project_environment import NodeJsProjectEnvironmentProcess
from pants.backend.javascript.package_json import PackageJsonTarget
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
from pants.build_graph.address import Address
from pants.engine.fs import DigestContents
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *install_node_package.rules(),
            *package_json.rules(),
            QueryRule(InstalledNodePackage, (InstalledNodePackageRequest,)),
            QueryRule(InstalledNodePackageWithSource, (InstalledNodePackageRequest,)),
            QueryRule(Process, (NodeJsProjectEnvironmentProcess,)),
            QueryRule(ProcessResult, (Process,)),
        ],
        target_types=[PackageJsonTarget, JSSourcesGeneratorTarget],
        objects=dict(package_json.build_file_aliases().objects),
    )


def test_install_node_package_with_extra_env_vars(rule_runner: RuleRunner) -> None:
    # Test both subsystem and target-level environment variables
    rule_runner.set_options(
        [
            "--nodejs-extra-env-vars=['GLOBAL_VAR=global_value', 'TARGET_VAR=will_be_overridden']",
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


def test_pnpm_installs_transitive_workspace_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.set_options([], env_inherit={"PATH"})
    rule_runner.write_files(
        {
            "src/js/BUILD": "package_json()",
            "src/js/package.json": json.dumps(
                {
                    "name": "root",
                    "version": "0.0.1",
                    "private": True,
                    "packageManager": "pnpm@9.15.4",
                }
            ),
            "src/js/pnpm-workspace.yaml": dedent(
                """\
                packages:
                  - 'ham'
                  - 'spam'
                  - 'egg'
                """
            ),
            "src/js/pnpm-lock.yaml": dedent(
                """\
                lockfileVersion: '9.0'

                settings:
                  autoInstallPeers: true
                  excludeLinksFromLockfile: false

                importers:

                  .: {}

                  egg: {}

                  ham:
                    dependencies:
                      spam:
                        specifier: workspace:*
                        version: link:../spam

                  spam:
                    dependencies:
                      egg:
                        specifier: workspace:*
                        version: link:../egg
                """
            ),
            "src/js/ham/BUILD": dedent(
                """\
                package_json(dependencies=[":js"])
                javascript_sources(name="js")
                """
            ),
            "src/js/ham/package.json": json.dumps(
                {
                    "name": "ham",
                    "version": "0.0.1",
                    "type": "module",
                    "dependencies": {"spam": "workspace:*"},
                }
            ),
            "src/js/ham/index.js": "import value from 'spam'; console.log(value);",
            "src/js/spam/BUILD": dedent(
                """\
                package_json(dependencies=[":js"])
                javascript_sources(name="js")
                """
            ),
            "src/js/spam/package.json": json.dumps(
                {
                    "name": "spam",
                    "version": "0.0.1",
                    "type": "module",
                    "main": "index.js",
                    "dependencies": {"egg": "workspace:*"},
                }
            ),
            "src/js/spam/index.js": "export { default } from 'egg';",
            "src/js/egg/BUILD": dedent(
                """\
                package_json(dependencies=[":js"])
                javascript_sources(name="js")
                """
            ),
            "src/js/egg/package.json": json.dumps(
                {"name": "egg", "version": "0.0.1", "type": "module", "main": "index.js"}
            ),
            "src/js/egg/index.js": "export default 42;",
        }
    )

    installed_package = rule_runner.request(
        InstalledNodePackageWithSource,
        [InstalledNodePackageRequest(Address("src/js/ham", generated_name="ham"))],
    )
    process = rule_runner.request(
        Process,
        [
            NodeJsProjectEnvironmentProcess(
                installed_package.project_env,
                ("exec", "node", "index.js"),
                description="Importing a workspace dependency of a workspace dependency.",
                input_digest=installed_package.digest,
            )
        ],
    )
    result = rule_runner.request(ProcessResult, [process])

    assert result.stdout == b"42\n"
