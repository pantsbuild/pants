# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import cast

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.subsystems import nodejs_tool
from pants.backend.javascript.target_types import JSSourcesGeneratorTarget
from pants.backend.typescript import check
from pants.backend.typescript.target_types import TypeScriptSourcesGeneratorTarget
from pants.backend.typescript.check import TypeScriptCheckRequest, TypeScriptCheckFieldSet
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResults
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner

@pytest.fixture(params=["npm", "pnpm", "yarn"])
def package_manager(request) -> str:
    return cast(str, request.param)


@pytest.fixture
def rule_runner(package_manager: str) -> RuleRunner:
    """Create RuleRunner following the successful nodejs_tool_test.py pattern."""
    rule_runner = RuleRunner(
        rules=[
            # Minimal rules following nodejs_tool_test.py pattern
            *nodejs_tool.rules(),
            *check.rules(),
            QueryRule(CheckResults, [TypeScriptCheckRequest]),
        ],
        target_types=[
            package_json.PackageJsonTarget,
            JSSourcesGeneratorTarget,
            TypeScriptSourcesGeneratorTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
        ],
        env_inherit={"PATH"},
    )
    return rule_runner


# Test content constants
SIMPLE_VALID_TS = textwrap.dedent(
    """\
    export function add(x: number, y: number): number {
        return x + y;
    }
    """
)

SIMPLE_INVALID_TS = textwrap.dedent(
    """\
    export function add(x: number, y: number): number {
        return x + "invalid"; // Type error: can't add string to number
    }
    """
)

TYPESCRIPT_TSCONFIG = json.dumps({
    "compilerOptions": {
        "target": "es2020",
        "module": "esnext", 
        "moduleResolution": "node",
        "strict": True,
        "esModuleInterop": True,
        "skipLibCheck": True,
        "forceConsistentCasingInFileNames": True,
        "outDir": "dist",
        "rootDir": "src"
    },
    "include": ["src/**/*"],
    "exclude": ["node_modules", "dist"]
})


def get_package_json_content() -> str:
    """Get package.json content from test_resources directory.
    
    This uses the same package.json that the lockfiles were generated from,
    ensuring consistency between package.json and lockfiles.
    """
    resource_path = Path(__file__).parent / "test_resources" / "package.json"
    return resource_path.read_text()


_LOCKFILE_FILE_NAMES = {
    "pnpm": "pnpm-lock.yaml",
    "npm": "package-lock.json",
    "yarn": "yarn.lock",
}


def _find_lockfile_resource(package_manager: str, resource_dir: str) -> dict[str, str]:
    """Find and read lockfile from test resources directory.
    
    Returns:
        Dict of {filename: content}
    """
    for file in (Path(__file__).parent / resource_dir).iterdir():
        if _LOCKFILE_FILE_NAMES.get(package_manager) == file.name:
            return {file.name: file.read_text()}
    raise AssertionError(
        f"No lockfile for {package_manager} set up in test resources directory {resource_dir}."
    )


@pytest.fixture
def typescript_lockfile(package_manager: str) -> dict[str, str]:
    """Get lockfile for TypeScript tests following JavaScript backend pattern."""
    return _find_lockfile_resource(package_manager, "test_resources")


@pytest.mark.platform_specific_behavior
def test_typescript_check_success(rule_runner: RuleRunner, package_manager: str, typescript_lockfile: dict[str, str]) -> None:
    """Test successful TypeScript type checking."""
    
    rule_runner.write_files(
        {
            "test_project/BUILD": "package_json(name='test_project')",
            "test_project/package.json": get_package_json_content(),
            "test_project/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "test_project/src/BUILD": "typescript_sources()",
            "test_project/src/math.ts": SIMPLE_VALID_TS,
            "test_project/src/index.ts": textwrap.dedent("""\
                import { add } from './math';
                
                export function calculate(): number {
                    return add(5, 10);
                }
            """),
            **{f"test_project/{filename}": content for filename, content in typescript_lockfile.items()},
        }
    )
    
    # Get the TypeScript target
    target = rule_runner.get_target(Address("test_project/src", relative_file_path="index.ts"))
    field_set = TypeScriptCheckFieldSet.create(target)
    
    # Create check request
    request = TypeScriptCheckRequest([field_set])
    
    # Execute the check
    results = rule_runner.request(CheckResults, [request])
    
    # Should succeed with no type errors
    assert len(results.results) == 1
    result = results.results[0]
    assert result.exit_code == 0
    assert "error" not in result.stdout.lower()


@pytest.mark.platform_specific_behavior  
def test_typescript_check_failure(rule_runner: RuleRunner, package_manager: str, typescript_lockfile: dict[str, str]) -> None:
    """Test TypeScript type checking with type errors."""
    
    rule_runner.write_files(
        {
            "test_project/BUILD": "package_json(name='test_project')",
            "test_project/package.json": get_package_json_content(),
            "test_project/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "test_project/src/BUILD": "typescript_sources()",
            "test_project/src/math.ts": SIMPLE_VALID_TS,
            "test_project/src/index.ts": textwrap.dedent("""\
                import { add } from './math';
                
                export function calculate(): number {
                    return add(5, "invalid"); // Type error: string not assignable to number
                }
            """),
            **{f"test_project/{filename}": content for filename, content in typescript_lockfile.items()},
        }
    )
    
    # Get the TypeScript target
    target = rule_runner.get_target(Address("test_project/src", relative_file_path="index.ts"))
    field_set = TypeScriptCheckFieldSet.create(target)
    
    # Create check request
    request = TypeScriptCheckRequest([field_set])
    
    # Execute the check
    results = rule_runner.request(CheckResults, [request])
    
    # Should fail with type errors
    assert len(results.results) == 1
    result = results.results[0]
    assert result.exit_code != 0
    assert "error" in result.stdout.lower()

