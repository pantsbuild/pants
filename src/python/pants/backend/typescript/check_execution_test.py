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
from pants.backend.tsx.target_types import (
    TSXSourcesGeneratorTarget,
    TSXTestsGeneratorTarget,
)
from pants.backend.typescript.check import (
    TypeScriptCheckRequest,
    TypeScriptCheckFieldSet,
)
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResults
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner

@pytest.fixture(params=[
    ("basic_project", "npm"),
    ("basic_project", "pnpm"), 
    ("basic_project", "yarn")
])
def basic_project_test(request) -> tuple[str, str]:
    """Basic project tests (all package managers)."""
    return cast(tuple[str, str], request.param)


@pytest.fixture(params=[
    ("complex_project", "npm"),
    ("complex_project", "yarn")
])
def workspace_project_test(request) -> tuple[str, str]:
    """Workspace project tests (npm/yarn only)."""
    return cast(tuple[str, str], request.param)


@pytest.fixture(params=[
    ("pnpm_link", "pnpm")
])
def pnpm_project_test(request) -> tuple[str, str]:
    """pnpm link protocol tests (pnpm only)."""
    return cast(tuple[str, str], request.param)


def _create_rule_runner(package_manager: str) -> RuleRunner:
    """Create RuleRunner with given package manager."""
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
            TSXSourcesGeneratorTarget,
            TSXTestsGeneratorTarget,
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


@pytest.fixture
def basic_rule_runner(basic_project_test: tuple[str, str]) -> tuple[RuleRunner, str, str]:
    """Create RuleRunner for basic project tests (all package managers)."""
    test_project, package_manager = basic_project_test
    return _create_rule_runner(package_manager), test_project, package_manager


@pytest.fixture  
def workspace_rule_runner(workspace_project_test: tuple[str, str]) -> tuple[RuleRunner, str, str]:
    """Create RuleRunner for workspace tests (npm/yarn only)."""
    test_project, package_manager = workspace_project_test
    return _create_rule_runner(package_manager), test_project, package_manager


@pytest.fixture
def pnpm_rule_runner(pnpm_project_test: tuple[str, str]) -> tuple[RuleRunner, str, str]:
    """Create RuleRunner for pnpm-specific tests."""
    test_project, package_manager = pnpm_project_test
    return _create_rule_runner(package_manager), test_project, package_manager


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


def _load_project_test_files(test_project: str) -> dict[str, str]:
    """Load test files for the specified project type."""
    base_dir = Path(__file__).parent / "test_resources" / test_project
    files = {}
    
    for file_path in base_dir.rglob("*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(base_dir)
            files[f"{test_project}/{relative_path}"] = file_path.read_text()
    
    return files


def test_typescript_check_success(basic_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test successful TypeScript type checking."""
    
    rule_runner, test_project, package_manager = basic_rule_runner
    
    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)
    
    target = rule_runner.get_target(Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts"))
    field_set = TypeScriptCheckFieldSet.create(target)
    
    request = TypeScriptCheckRequest([field_set])
    results = rule_runner.request(CheckResults, [request])
    
    assert len(results.results) == 1
    assert results.results[0].exit_code == 0


def test_typescript_check_failure(basic_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test TypeScript type checking with type errors."""
    
    rule_runner, test_project, package_manager = basic_rule_runner
    
    # Load base project files and override index.ts with type error
    test_files = _load_project_test_files(test_project)
    test_files["basic_project/src/index.ts"] = textwrap.dedent("""\
        import { add } from './math';
        
        export function calculate(): number {
            return add(5, "invalid"); // Type error: string not assignable to number
        }
    """)
    
    rule_runner.write_files(test_files)
        
    target = rule_runner.get_target(Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts"))
    field_set = TypeScriptCheckFieldSet.create(target)
    
    request = TypeScriptCheckRequest([field_set])
    results = rule_runner.request(CheckResults, [request])
    
    assert len(results.results) == 1
    assert results.results[0].exit_code != 0



def test_typescript_check_no_targets_in_project(basic_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test project with no TypeScript targets."""
    
    rule_runner, test_project, package_manager = basic_rule_runner
    
    # Load base project but override to have only JS sources
    test_files = _load_project_test_files(test_project)
    test_files["basic_project/src/BUILD"] = "javascript_sources()"  # Only JS sources, no TS
    test_files["basic_project/src/index.js"] = "console.log('Hello from JS');"
    del test_files["basic_project/src/index.ts"]
    
    rule_runner.write_files(test_files)
    
    # Create an empty request since there are no TS targets
    request = TypeScriptCheckRequest([])
    results = rule_runner.request(CheckResults, [request])
    
    assert len(results.results) == 0




def test_typescript_check_multiple_projects(workspace_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test checking targets across multiple projects (workspace structure)."""
    
    rule_runner, test_project, package_manager = workspace_rule_runner
    
    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)
    
    # Get targets from different packages in the workspace to simulate multiple projects
    common_types_target = rule_runner.get_target(Address("complex_project/common-types/src", relative_file_path="index.ts"))
    shared_utils_target = rule_runner.get_target(Address("complex_project/shared-utils/src", target_name="ts_sources", relative_file_path="math.ts"))
    main_app_target = rule_runner.get_target(Address("complex_project/main-app/src", relative_file_path="index.ts"))
    
    field_setA = TypeScriptCheckFieldSet.create(common_types_target)
    field_setB = TypeScriptCheckFieldSet.create(shared_utils_target)
    field_setC = TypeScriptCheckFieldSet.create(main_app_target)
    
    request = TypeScriptCheckRequest([field_setA, field_setB, field_setC])
    results = rule_runner.request(CheckResults, [request])
    
    # Should have results for the packages (could be combined or separate depending on Pants optimization)
    assert len(results.results) >= 1
    
    for result in results.results:
        assert result.exit_code == 0
        assert "error" not in result.stdout.lower()


def test_typescript_check_test_files(workspace_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test TypeScript test files using typescript_tests target (workspace structure)."""
    
    rule_runner, test_project, package_manager = workspace_rule_runner
    
    # Load complex project and add test files
    test_files = _load_project_test_files(test_project)
    test_files.update({
        "complex_project/main-app/tests/BUILD": "typescript_tests()",
        "complex_project/main-app/tests/math.test.ts": textwrap.dedent("""
            import { add } from '@test/shared-utils';
            
            // Test file imports should work
            const result = add(2, 3);
            console.log(`Test result: ${result}`);
        """),
    })
    
    rule_runner.write_files(test_files)
    
    test_target = rule_runner.get_target(Address("complex_project/main-app/tests", relative_file_path="math.test.ts"))
    test_field_set = TypeScriptCheckFieldSet.create(test_target)
    
    request = TypeScriptCheckRequest([test_field_set])
    results = rule_runner.request(CheckResults, [request])
    
    assert len(results.results) == 1
    assert results.results[0].exit_code == 0


def test_typescript_check_cross_project_imports(basic_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test that cross-project imports fail as expected (projects are compiled in isolation)."""
    
    rule_runner, test_project, package_manager = basic_rule_runner
    
    # Simplify to test imports that should fail within a single workspace
    # by trying to import from a non-workspace path
    test_files = _load_project_test_files(test_project)
    
    # Override to try importing from an invalid path
    test_files["src/index.ts"] = textwrap.dedent("""
        // This import should fail - trying to import from non-existent external path
        import { nonExistentFunction } from '../../external-project/src/shared';
        
        export function useExternal(): string {
            return nonExistentFunction('test');
        }
    """)
    
    rule_runner.write_files(test_files)
    
    cross_import_target = rule_runner.get_target(Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts"))
    cross_import_field_set = TypeScriptCheckFieldSet.create(cross_import_target)
    
    request = TypeScriptCheckRequest([cross_import_field_set])
    results = rule_runner.request(CheckResults, [request])
    
    # Should fail due to module resolution error (can't find invalid import)
    assert len(results.results) == 1
    result = results.results[0]
    
    # TypeScript should fail to resolve the invalid import
    assert result.exit_code != 0
    
    # Should contain TypeScript's specific "Cannot find module" error (TS2307)
    error_output = result.stdout + result.stderr
    assert "TS2307" in error_output and "Cannot find module" in error_output


def test_typescript_check_pnpm_link_protocol_success(pnpm_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test that pnpm link: protocol allows successful imports between packages."""
    
    rule_runner, test_project, package_manager = pnpm_rule_runner
    
    # Load project files (pnpm_link uses special test prefix)
    test_files = _load_project_test_files(test_project)
    
    rule_runner.write_files(test_files)
    
    parent_target = rule_runner.get_target(Address("pnpm_link/src", relative_file_path="main.ts"))
    parent_field_set = TypeScriptCheckFieldSet.create(parent_target)
    
    request = TypeScriptCheckRequest([parent_field_set])
    results = rule_runner.request(CheckResults, [request])
    
    # Should succeed - pnpm link: protocol should resolve with hoisted configuration
    assert len(results.results) == 1
    assert results.results[0].exit_code == 0, f"TypeScript check failed: {results.results[0].stdout}\n{results.results[0].stderr}"


def test_typescript_check_tsx_files(basic_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test TypeScript compilation of .tsx files with React components."""
    
    rule_runner, test_project, package_manager = basic_rule_runner
    
    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)
    
    tsx_target = rule_runner.get_target(Address("basic_project/src", target_name="tsx_sources", relative_file_path="Button.tsx"))
    tsx_field_set = TypeScriptCheckFieldSet.create(tsx_target)
    
    request = TypeScriptCheckRequest([tsx_field_set])
    results = rule_runner.request(CheckResults, [request])
    
    # TSX compilation should work with React types
    assert len(results.results) == 1
    assert results.results[0].exit_code == 0, f"TypeScript check of TSX failed: {results.results[0].stdout}\n{results.results[0].stderr}"

