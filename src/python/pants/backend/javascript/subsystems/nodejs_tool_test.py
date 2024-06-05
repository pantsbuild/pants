# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

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
            "--nodejs-package-managers={'npm': '10.8.1', 'yarn': '1.22.22', 'pnpm': '7.33.7'}",
        ],
        env_inherit={"PATH"},
    )
    tool = rule_runner.request(CowsayTool, [])

    request = tool.request(("--version",), EMPTY_DIGEST, "Cowsay version", LogLevel.DEBUG)

    to_run = rule_runner.request(Process, [request])

    assert to_run.argv == expected_argv + ("cowsay@1.5.0", "--version")

    result = rule_runner.request(ProcessResult, [request])

    assert result.stdout == b"1.6.0\n"


@pytest.mark.parametrize(
    "lockfile_path, package_manager, package_manager_version",
    [
        pytest.param(Path(__file__).parent / "yarn.lock", "yarn", "1.22.22", id="yarn_resolve"),
        pytest.param(Path(__file__).parent / "pnpm-lock.yaml", "pnpm", "7.33.7", id="pnpm_resolve"),
        pytest.param(Path(__file__).parent / "package-lock.json", "npm", "10.8.1",  id="npm_resolve"),
    ],
)
def test_resolve_dictates_version(
    rule_runner: RuleRunner, lockfile_path: Path, package_manager: str, package_manager_version: str
):
    rule_runner.write_files(
        {
            "BUILD": "package_json(name='root_pkg')",
            "package.json": json.dumps(
                {
                    "name": "@the-company/project",
                    "devDependencies": {"cowsay": "1.6.0"},
                    "packageManager": f"{package_manager}@{package_manager_version}"
                },
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
