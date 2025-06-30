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
from pants.backend.typescript.target_types import (
    TypeScriptSourcesGeneratorTarget,
    TypeScriptTestsGeneratorTarget,
)
from pants.backend.typescript.check import (
    TypeScriptCheckRequest,
    TypeScriptCheckFieldSet,
)
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
            TypeScriptTestsGeneratorTarget,
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


def get_pnpm_workspace_content() -> str:
    """Get pnpm-workspace.yaml content from test_resources directory.
    
    This ensures consistent pnpm workspace configuration with hoisted node linking.
    """
    resource_path = Path(__file__).parent / "test_resources" / "pnpm-workspace.yaml"
    return resource_path.read_text()


def _load_pnpm_link_test_files() -> dict[str, str]:
    """Load test files for pnpm link: protocol test from resources with test directory prefix."""
    base_dir = Path(__file__).parent / "test_resources" / "pnpm_link"
    files = {}
    
    # Load all files recursively, adding test directory prefix
    for file_path in base_dir.rglob("*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(base_dir)
            files[f"pnpm_link_test/{relative_path}"] = file_path.read_text()
    
    return files


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


def test_typescript_check_skip_field(rule_runner: RuleRunner, package_manager: str, typescript_lockfile: dict[str, str]) -> None:
    """Test that targets with skip_typescript_check=true are skipped."""
    
    rule_runner.write_files(
        {
            "test_project/BUILD": "package_json(name='test_project')",
            "test_project/package.json": get_package_json_content(),
            "test_project/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "test_project/src/BUILD": textwrap.dedent("""
                typescript_sources(
                    name="normal",
                    sources=["math.ts"],
                )
                typescript_sources(
                    name="skipped",
                    sources=["index.ts"],
                    skip_typescript_check=True,
                )
            """),
            "test_project/src/math.ts": SIMPLE_VALID_TS,
            "test_project/src/index.ts": SIMPLE_INVALID_TS,  # Has type error but should be skipped
            **{f"test_project/{filename}": content for filename, content in typescript_lockfile.items()},
        }
    )
    
    # Get both targets
    normal_target = rule_runner.get_target(Address("test_project/src", target_name="normal", relative_file_path="math.ts"))
    skipped_target = rule_runner.get_target(Address("test_project/src", target_name="skipped", relative_file_path="index.ts"))
    
    # Debug: Check if the skip field is available on targets
    from pants.backend.typescript.check import SkipTypeScriptCheckField
    
    # Check the generator targets have the field
    normal_generator = rule_runner.get_target(Address("test_project/src", target_name="normal"))
    skipped_generator = rule_runner.get_target(Address("test_project/src", target_name="skipped"))
    
    assert not normal_generator.get(SkipTypeScriptCheckField).value
    assert skipped_generator.get(SkipTypeScriptCheckField).value
    
    # Check individual targets inherit the field  
    assert not normal_target.get(SkipTypeScriptCheckField).value
    assert skipped_target.get(SkipTypeScriptCheckField).value
    
    # Verify the skipped target opts out
    assert not TypeScriptCheckFieldSet.opt_out(normal_target)
    assert TypeScriptCheckFieldSet.opt_out(skipped_target)
    
    # Create field set for normal target
    normal_field_set = TypeScriptCheckFieldSet.create(normal_target)
    
    # Check only the normal target - skipped one should not cause failure
    request = TypeScriptCheckRequest([normal_field_set])
    results = rule_runner.request(CheckResults, [request])
    
    # Should succeed since we only checked the valid file
    assert len(results.results) == 1
    result = results.results[0]
    
    assert result.exit_code == 0
    assert "error" not in result.stdout.lower()


def test_typescript_check_no_targets_in_project(rule_runner: RuleRunner, typescript_lockfile: dict[str, str]) -> None:
    """Test project with no TypeScript targets."""
    
    rule_runner.write_files(
        {
            "test_project/BUILD": "package_json(name='test_project')",
            "test_project/package.json": get_package_json_content(),
            "test_project/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "test_project/src/BUILD": "javascript_sources()",  # Only JS sources, no TS
            "test_project/src/index.js": "console.log('Hello from JS');",
            **{f"test_project/{filename}": content for filename, content in typescript_lockfile.items()},
        }
    )
    
    # Try to get TypeScript targets - there should be none
    # We need to create an empty request since there are no TS targets
    request = TypeScriptCheckRequest([])
    results = rule_runner.request(CheckResults, [request])
    
    # Should return empty results when no field sets provided
    assert len(results.results) == 0


def test_typescript_check_subsystem_skip(rule_runner: RuleRunner, typescript_lockfile: dict[str, str]) -> None:
    """Test global TypeScript skip via --typescript-skip option."""
    
    # Set the skip option
    rule_runner.set_options(
        [
            "--typescript-skip",  # Skip all TypeScript checking
        ],
        env_inherit={"PATH"},
    )
    
    rule_runner.write_files(
        {
            "test_project/BUILD": "package_json(name='test_project')",
            "test_project/package.json": get_package_json_content(),
            "test_project/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "test_project/src/BUILD": "typescript_sources()",
            "test_project/src/index.ts": SIMPLE_INVALID_TS,  # Has type error but checking is skipped
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
    
    # Should return empty results due to subsystem skip
    assert len(results.results) == 0


def test_typescript_check_multiple_projects(rule_runner: RuleRunner, typescript_lockfile: dict[str, str]) -> None:
    """Test checking targets across multiple projects."""
    
    rule_runner.write_files(
        {
            # Project A
            "projectA/BUILD": "package_json(name='projectA')",
            "projectA/package.json": get_package_json_content(),
            "projectA/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "projectA/src/BUILD": "typescript_sources()",
            "projectA/src/math.ts": SIMPLE_VALID_TS,
            **{f"projectA/{filename}": content for filename, content in typescript_lockfile.items()},
            
            # Project B  
            "projectB/BUILD": "package_json(name='projectB')",
            "projectB/package.json": get_package_json_content(),
            "projectB/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "projectB/src/BUILD": "typescript_sources()",
            "projectB/src/utils.ts": textwrap.dedent("""
                export function multiply(x: number, y: number): number {
                    return x * y;
                }
            """),
            **{f"projectB/{filename}": content for filename, content in typescript_lockfile.items()},
        }
    )
    
    # Get targets from both projects
    targetA = rule_runner.get_target(Address("projectA/src", relative_file_path="math.ts"))
    targetB = rule_runner.get_target(Address("projectB/src", relative_file_path="utils.ts"))
    
    field_setA = TypeScriptCheckFieldSet.create(targetA)
    field_setB = TypeScriptCheckFieldSet.create(targetB)
    
    # Create check request with targets from both projects
    request = TypeScriptCheckRequest([field_setA, field_setB])
    
    # Execute the check
    results = rule_runner.request(CheckResults, [request])
    
    # Should have 2 results, one for each project
    assert len(results.results) == 2
    
    # Both should succeed
    for result in results.results:
        assert result.exit_code == 0
        assert "error" not in result.stdout.lower()
        
    # Verify partition descriptions mention different projects
    partitions = [r.partition_description for r in results.results]
    assert any("projectA" in p for p in partitions if p)
    assert any("projectB" in p for p in partitions if p)


def test_typescript_check_test_files(rule_runner: RuleRunner, typescript_lockfile: dict[str, str]) -> None:
    """Test TypeScript test files using typescript_tests target."""
    
    rule_runner.write_files(
        {
            "test_project/BUILD": "package_json(name='test_project')",
            "test_project/package.json": get_package_json_content(),
            "test_project/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "test_project/src/BUILD": "typescript_sources()",
            "test_project/src/math.ts": SIMPLE_VALID_TS,
            "test_project/tests/BUILD": "typescript_tests()",
            "test_project/tests/math.test.ts": textwrap.dedent("""
                import { add } from '../src/math';
                
                // Test file imports should work
                const result = add(2, 3);
                console.log(`Test result: ${result}`);
            """),
            **{f"test_project/{filename}": content for filename, content in typescript_lockfile.items()},
        }
    )
    
    # Get the test target - TypeScript tests are also handled by TypeScriptCheckFieldSet
    test_target = rule_runner.get_target(Address("test_project/tests", relative_file_path="math.test.ts"))
    test_field_set = TypeScriptCheckFieldSet.create(test_target)
    
    # Create check request
    request = TypeScriptCheckRequest([test_field_set])
    
    # Execute the check
    results = rule_runner.request(CheckResults, [request])
    
    # Should succeed
    assert len(results.results) == 1
    result = results.results[0]
    assert result.exit_code == 0
    assert "error" not in result.stdout.lower()


def test_typescript_check_cross_project_imports(rule_runner: RuleRunner, typescript_lockfile: dict[str, str]) -> None:
    """Test that cross-project imports fail as expected (projects are compiled in isolation)."""
    
    rule_runner.write_files(
        {
            # Project A with shared utility
            "projectA/BUILD": "package_json(name='projectA')",
            "projectA/package.json": get_package_json_content(),
            "projectA/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "projectA/src/BUILD": "typescript_sources()",
            "projectA/src/shared.ts": textwrap.dedent("""
                export function sharedFunction(value: string): string {
                    return `Shared: ${value}`;
                }
            """),
            **{f"projectA/{filename}": content for filename, content in typescript_lockfile.items()},
            
            # Project B trying to import from Project A (should fail)
            "projectB/BUILD": "package_json(name='projectB')",
            "projectB/package.json": get_package_json_content(),
            "projectB/tsconfig.json": TYPESCRIPT_TSCONFIG,
            "projectB/src/BUILD": "typescript_sources()",
            "projectB/src/consumer.ts": textwrap.dedent("""
                // This import should fail - cross-project imports not supported
                import { sharedFunction } from '../../projectA/src/shared';
                
                export function useShared(): string {
                    return sharedFunction('test');
                }
            """),
            **{f"projectB/{filename}": content for filename, content in typescript_lockfile.items()},
        }
    )
    
    # Get the target that attempts cross-project import
    cross_import_target = rule_runner.get_target(Address("projectB/src", relative_file_path="consumer.ts"))
    cross_import_field_set = TypeScriptCheckFieldSet.create(cross_import_target)
    
    # Create check request for the target with cross-project import
    request = TypeScriptCheckRequest([cross_import_field_set])
    
    # Execute the check
    results = rule_runner.request(CheckResults, [request])
    
    # Should fail due to module resolution error (can't find cross-project import)
    assert len(results.results) == 1
    result = results.results[0]
    
    # TypeScript should fail to resolve the cross-project import
    assert result.exit_code != 0
    
    # Should contain TypeScript's specific "Cannot find module" error (TS2307)
    # TypeScript outputs: "error TS2307: Cannot find module '../../projectA/src/shared' or its corresponding type declarations."
    error_output = result.stdout + result.stderr
    assert "TS2307" in error_output and "Cannot find module" in error_output


def test_typescript_check_pnpm_link_protocol_success(rule_runner: RuleRunner, package_manager: str) -> None:
    """Test that pnpm link: protocol allows successful imports between packages."""
    
    # Only run this test with pnpm
    if package_manager != "pnpm":
        pytest.skip("This test is specific to pnpm link: protocol")
    
    # Load all test files from test_resources/pnpm_link directory (with test prefix applied)
    test_files = _load_pnpm_link_test_files()
    
    rule_runner.write_files(test_files)
    
    # Get the parent target that imports from child via link: protocol
    parent_target = rule_runner.get_target(Address("pnpm_link_test/src", relative_file_path="main.ts"))
    parent_field_set = TypeScriptCheckFieldSet.create(parent_target)
    
    # Create check request
    request = TypeScriptCheckRequest([parent_field_set])
    
    # Execute the check
    results = rule_runner.request(CheckResults, [request])
    
    # Should succeed - pnpm link: protocol should resolve with hoisted configuration
    assert len(results.results) == 1
    result = results.results[0]
    assert result.exit_code == 0, f"TypeScript check failed: {result.stdout}\n{result.stderr}"

