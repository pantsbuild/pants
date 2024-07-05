# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from pants.backend.javascript.package_json import PackageJsonTarget
from pants.backend.javascript.subsystems import nodejs_tool
from pants.backend.javascript.subsystems.nodejs_tool import NodeJSToolBase, NodeJSToolRequest
from pants.engine.internals.native_engine import EMPTY_DIGEST
from pants.engine.process import Process, ProcessResult
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.logging import LogLevel


class CowsayTool(NodeJSToolBase):
    options_scope = "cowsay"
    name = "Cowsay"
    # Intentionally older version.
    default_version = "cowsay@1.4.0"
    help = "The Cowsay utility for printing cowsay messages"


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *nodejs_tool.rules(),
            *CowsayTool.rules(),
            QueryRule(CowsayTool, []),
            QueryRule(ProcessResult, [NodeJSToolRequest]),
            QueryRule(Process, [NodeJSToolRequest]),
            QueryRule(ProcessResult, [Process]),
        ],
        target_types=[PackageJsonTarget],
    )


def test_version_option_overrides_default(rule_runner: RuleRunner):
    rule_runner.set_options(["--cowsay-version=cowsay@1.6.0"], env_inherit={"PATH"})
    tool = rule_runner.request(CowsayTool, [])
    assert tool.default_version == "cowsay@1.4.0"
    assert tool.version == "cowsay@1.6.0"


@pytest.mark.parametrize(
    "package_manager, expected_argv",
    [
        pytest.param("yarn", ("yarn", "dlx", "--quiet"), id="yarn"),
        pytest.param("npm", ("npm", "exec", "--yes", "--"), id="npm"),
        pytest.param("pnpm", ("pnpm", "dlx"), id="pnpm"),
    ],
)
def test_execute_process_with_package_manager(
    rule_runner: RuleRunner,
    package_manager: str,
    expected_argv: tuple[str, ...],
):
    rule_runner.set_options(
        [
            "--cowsay-version=cowsay@1.6.0",
            f"--nodejs-package-manager={package_manager}",
        ],
        env_inherit={"PATH"},
    )
    tool = rule_runner.request(CowsayTool, [])

    request = tool.request(("--version",), EMPTY_DIGEST, "Cowsay version", LogLevel.DEBUG)

    to_run = rule_runner.request(Process, [request])

    assert to_run.argv == expected_argv + ("cowsay@1.6.0", "--version")

    result = rule_runner.request(ProcessResult, [request])

    assert result.stdout == b"1.6.0\n"


@pytest.mark.parametrize(
    "package_manager, version",
    [
        pytest.param("yarn", "1.22.22", id="yarn"),
        pytest.param("npm", "10.8.1", id="npm"),
        pytest.param("pnpm", "8.15.8", id="pnpm"),
    ],
)
def test_execute_process_with_package_manager_version_from_configuration(
    rule_runner: RuleRunner,
    package_manager: str,
    version: str,
):
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            f"--nodejs-package-managers={{'{package_manager}': '{version}'}}",
        ],
        env_inherit={"PATH"},
    )

    tool = rule_runner.request(CowsayTool, [])

    result = request_package_manager_version_for_tool(tool, package_manager, rule_runner)

    assert result == version


@pytest.mark.parametrize(
    "lockfile_path, package_manager, version",
    [
        pytest.param(Path(__file__).parent / "yarn.lock", "yarn", "1.22.22", id="yarn_resolve"),
        pytest.param(Path(__file__).parent / "pnpm-lock.yaml", "pnpm", "8.15.8", id="pnpm_resolve"),
        pytest.param(
            Path(__file__).parent / "package-lock.json", "npm", "10.8.1", id="npm_resolve"
        ),
    ],
)
def test_execute_process_with_package_manager_version_from_resolve_package_manager(
    rule_runner: RuleRunner,
    lockfile_path: Path,
    package_manager: str,
    version: str,
):
    rule_runner.set_options(
        [
            "--nodejs-package-managers={}",
            "--cowsay-install-from-resolve=nodejs-default",
        ],
        env_inherit={"PATH"},
    )
    rule_runner.write_files(
        {
            "BUILD": "package_json(name='root_pkg')",
            "package.json": json.dumps(
                {
                    "name": "@the-company/project",
                    "devDependencies": {"cowsay": "^1.6.0"},
                    "packageManager": f"{package_manager}@{version}",
                }
            ),
            lockfile_path.name: lockfile_path.read_text(),
        }
    )
    tool = rule_runner.request(CowsayTool, [])

    result = request_package_manager_version_for_tool(tool, package_manager, rule_runner)

    assert result == version


@pytest.mark.parametrize(
    "lockfile_path, package_manager",
    [
        pytest.param(Path(__file__).parent / "yarn.lock", "yarn", id="yarn_resolve"),
        pytest.param(Path(__file__).parent / "pnpm-lock.yaml", "pnpm", id="pnpm_resolve"),
        pytest.param(Path(__file__).parent / "package-lock.json", "npm", id="npm_resolve"),
    ],
)
def test_resolve_dictates_version(
    rule_runner: RuleRunner, lockfile_path: Path, package_manager: str
):
    rule_runner.write_files(
        {
            "BUILD": "package_json(name='root_pkg')",
            "package.json": json.dumps(
                {"name": "@the-company/project", "devDependencies": {"cowsay": "^1.6.0"}}
            ),
            lockfile_path.name: lockfile_path.read_text(),
        }
    )
    rule_runner.set_options(
        [
            "--cowsay-install-from-resolve=nodejs-default",
            f"--nodejs-package-manager={package_manager}",
        ],
        env_inherit={"PATH"},
    )
    tool = rule_runner.request(CowsayTool, [])
    result = rule_runner.request(
        ProcessResult,
        [tool.request(("--version",), EMPTY_DIGEST, "Cowsay version", LogLevel.DEBUG)],
    )

    assert result.stdout == b"1.6.0\n"


def request_package_manager_version_for_tool(
    tool: NodeJSToolBase, package_manager: str, rule_runner: RuleRunner
) -> str:
    request = tool.request((), EMPTY_DIGEST, "Inspect package manager version", LogLevel.DEBUG)
    process = rule_runner.request(Process, [request])
    result = rule_runner.request(
        ProcessResult,
        [dataclasses.replace(process, argv=(package_manager, "--version"))],
    )
    return result.stdout.decode().strip()
