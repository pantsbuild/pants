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


class TypescriptTool(NodeJSToolBase):
    options_scope = "typescript"
    name = "TypeScript"
    default_version = "typescript@5.8.3"
    help = "The TypeScript compiler"


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *nodejs_tool.rules(),
            *CowsayTool.rules(),
            *TypescriptTool.rules(),
            QueryRule(CowsayTool, []),
            QueryRule(TypescriptTool, []),
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
        pytest.param(
            "yarn",
            ("yarn", "dlx", "--quiet", "--package", "cowsay@1.6.0", "cowsay", "--version"),
            id="yarn",
        ),
        pytest.param(
            "npm",
            ("npm", "exec", "--yes", "--package", "cowsay@1.6.0", "--", "cowsay", "--version"),
            id="npm",
        ),
        pytest.param(
            "pnpm", ("pnpm", "--package", "cowsay@1.6.0", "dlx", "cowsay", "--version"), id="pnpm"
        ),
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

    assert to_run.argv == expected_argv

    result = rule_runner.request(ProcessResult, [request])

    assert result.stdout == b"1.6.0\n"


@pytest.mark.parametrize(
    "package_manager, version",
    [
        pytest.param("yarn", "1.22.22", id="yarn"),
        pytest.param("npm", "10.9.2", id="npm"),
        pytest.param("pnpm", "9.15.6", id="pnpm"),
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
        pytest.param(Path(__file__).parent / "pnpm-lock.yaml", "pnpm", "9.15.6", id="pnpm_resolve"),
        pytest.param(
            Path(__file__).parent / "package-lock.json", "npm", "10.9.2", id="npm_resolve"
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


@pytest.mark.parametrize(
    "package_manager, expected_argv",
    [
        pytest.param(
            "yarn",
            ("yarn", "dlx", "--quiet", "--package", "typescript@5.8.3", "tsc", "--version"),
            id="yarn",
        ),
        pytest.param(
            "npm",
            ("npm", "exec", "--yes", "--package", "typescript@5.8.3", "--", "tsc", "--version"),
            id="npm",
        ),
        pytest.param(
            "pnpm",
            ("pnpm", "--package", "typescript@5.8.3", "dlx", "tsc", "--version"),
            id="pnpm",
        ),
    ],
)
def test_execute_packaged_tool_with_binary_name_override(
    rule_runner: RuleRunner,
    package_manager: str,
    expected_argv: tuple[str, ...],
):
    rule_runner.set_options(
        [
            "--typescript-version=typescript@5.8.3",
            "--typescript-binary-name=tsc",
            f"--nodejs-package-manager={package_manager}",
        ],
        env_inherit={"PATH"},
    )
    tool = rule_runner.request(TypescriptTool, [])
    request = tool.request(("--version",), EMPTY_DIGEST, "TypeScript version", LogLevel.DEBUG)
    to_run = rule_runner.request(Process, [request])
    assert to_run.argv == expected_argv


def test_scoped_npm_package_binary_name():
    """Test that scoped npm packages have their binary name extracted correctly."""

    class TestTool(NodeJSToolBase):
        options_scope = "test_tool"
        name = "TestTool"
        default_version = ""
        help = "Test tool"

        def __init__(self, version, binary_name_override=None):
            self.version = version
            self._binary_name = binary_name_override

    # Test with explicit binary name override
    tool_with_override = TestTool("@angular/cli@17.0.0", "ng")
    assert tool_with_override.binary_name == "ng"

    # Test default behavior for scoped package
    # For scoped packages, we use the scope name as a reasonable default
    tool_scoped = TestTool("@angular/cli@17.0.0")
    assert tool_scoped.binary_name == "angular"

    # Test regular package
    tool_regular = TestTool("cowsay@1.4.0")
    assert tool_regular.binary_name == "cowsay"

    # Test scoped package without version
    tool_scoped_no_version = TestTool("@angular/cli")
    assert tool_scoped_no_version.binary_name == "angular"

    # Test various version specifiers
    tool_latest = TestTool("package@latest")
    assert tool_latest.binary_name == "package"

    tool_beta = TestTool("@scope/package@1.2.3-beta.1")
    assert tool_beta.binary_name == "scope"

    tool_range = TestTool("package@^1.2.3")
    assert tool_range.binary_name == "package"


def test_invalid_npm_package_specification():
    """Test that invalid npm package specifications raise clear errors."""
    import pytest

    class TestTool(NodeJSToolBase):
        options_scope = "test_tool"
        name = "TestTool"
        default_version = ""
        help = "Test tool"

        def __init__(self, version):
            self.version = version
            self._binary_name = None

    tool_invalid = TestTool("")
    with pytest.raises(ValueError, match="Invalid npm package specification: "):
        _ = tool_invalid.binary_name
