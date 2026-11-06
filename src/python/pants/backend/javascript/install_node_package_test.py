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
from pants.engine.process import FallibleProcessResult, Process
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
            QueryRule(FallibleProcessResult, (Process,)),
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
    files = {
        "src/js/BUILD": "package_json()",
        "src/js/package.json": json.dumps(
            {
                "name": "root",
                "private": True,
                "packageManager": "pnpm@9.15.4",
                "workspaces": ["packages/*"],
            }
        ),
        "src/js/pnpm-workspace.yaml": "packages:\n  - 'packages/*'\n",
        "src/js/pnpm-lock.yaml": dedent("""\
            lockfileVersion: '9.0'
            settings:
              autoInstallPeers: true
              excludeLinksFromLockfile: false
            importers:
              .: {}
              packages/reader:
                dependencies:
                  '@invented/contract':
                    specifier: workspace:*
                    version: link:../contract
              packages/contract:
                dependencies:
                  '@invented/leaf':
                    specifier: workspace:*
                    version: link:../leaf
              packages/leaf: {}
        """),
    }
    for name, dependency, source in (
        ("reader", "contract", "import value from '@invented/contract'; console.log(value);"),
        ("contract", "leaf", "export {default} from '@invented/leaf';"),
        ("leaf", None, "export default 42;"),
    ):
        directory = f"src/js/packages/{name}"
        manifest: dict[str, object] = {
            "name": f"@invented/{name}",
            "version": "1.0.0",
            "main": "index.js",
            "type": "module",
        }
        if dependency:
            manifest["dependencies"] = {f"@invented/{dependency}": "workspace:*"}
        files[f"{directory}/BUILD"] = (
            'package_json(dependencies=[":sources"])\njavascript_sources(name="sources")'
        )
        files[f"{directory}/package.json"] = json.dumps(manifest)
        files[f"{directory}/index.js"] = source
    rule_runner.write_files(files)
    installed = rule_runner.request(
        InstalledNodePackageWithSource,
        [
            InstalledNodePackageRequest(
                Address("src/js/packages/reader", generated_name="__invented/reader")
            )
        ],
    )
    contents = rule_runner.request(DigestContents, [installed.digest])
    paths = {entry.path for entry in contents}
    assert {f"src/js/packages/{name}/index.js" for name in ("reader", "contract", "leaf")} <= paths
    process = rule_runner.request(
        Process,
        [
            NodeJsProjectEnvironmentProcess(
                installed.project_env,
                ("exec", "node", "index.js"),
                description="Load a dependency through another workspace package.",
                input_digest=installed.digest,
            )
        ],
    )
    result = rule_runner.request(FallibleProcessResult, [process])
    assert result.exit_code == 0, result.stderr.decode()
    assert result.stdout == b"42\n"
