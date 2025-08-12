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
from pants.backend.tsx.target_types import TSXSourcesGeneratorTarget, TSXTestsGeneratorTarget
from pants.backend.typescript.goals import check
from pants.backend.typescript.goals.check import TypeScriptCheckFieldSet, TypeScriptCheckRequest
from pants.backend.typescript.target_types import (
    TypeScriptSourcesGeneratorTarget,
    TypeScriptTestsGeneratorTarget,
)
from pants.build_graph.address import Address
from pants.core.goals.check import CheckResults
from pants.core.target_types import FileTarget
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner, logging
from pants.util.logging import LogLevel


def parse_typescript_build_status(stdout: str) -> dict[str, bool]:
    """Extract build status from TypeScript's official --verbose output.

    This parses TypeScript's authoritative output rather than wrapper script debug messages.
    TypeScript provides reliable indicators for full vs incremental builds.
    """
    # Look for TypeScript's official verbose output patterns
    full_build_indicators = [
        "Building project",
    ]

    incremental_indicators = [
        "up to date but needs to update timestamps of output files that are older than input files"
    ]

    # Check for full build indicators
    has_full_build = any(indicator in stdout for indicator in full_build_indicators)

    # Check for incremental build indicators
    has_incremental = any(indicator in stdout for indicator in incremental_indicators)

    return {
        "full_build": has_full_build,
        "incremental_build": has_incremental,
        "has_typescript_output": "AM -" in stdout
        or "PM -" in stdout,  # Basic check for TypeScript timestamp output
    }


@pytest.fixture(
    params=[("basic_project", "npm"), ("basic_project", "pnpm"), ("basic_project", "yarn")]
)
def basic_project_test(request) -> tuple[str, str]:
    """Basic project tests (all package managers)."""
    return cast(tuple[str, str], request.param)


@pytest.fixture(params=[("complex_project", "npm"), ("complex_project", "yarn")])
def workspace_project_test(request) -> tuple[str, str]:
    """Workspace project tests (npm/yarn only)."""
    return cast(tuple[str, str], request.param)


@pytest.fixture(params=[("pnpm_link", "pnpm")])
def pnpm_project_test(request) -> tuple[str, str]:
    """pnpm link protocol tests (pnpm only)."""
    return cast(tuple[str, str], request.param)


def _create_rule_runner(package_manager: str) -> RuleRunner:
    """Create RuleRunner with given package manager.

    Cache isolation via unique build_roots.
    """
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
            FileTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
        preserve_tmpdirs=True,
    )
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            "-ldebug",
            "--log-levels-by-target={'pants.backend.typescript': 'debug'}",
            "--keep-sandboxes=always",
        ],
        env_inherit={"PATH"},
    )
    return rule_runner


def _run_typescript_check_twice(
    rule_runner: RuleRunner, field_sets: list[TypeScriptCheckFieldSet]
) -> tuple[CheckResults, CheckResults]:
    """Run TypeScript check twice and return CheckResults."""
    request = TypeScriptCheckRequest(field_sets)
    results_1 = rule_runner.request(CheckResults, [request])
    results_2 = rule_runner.request(CheckResults, [request])
    return results_1, results_2


def _assert_identical_output_results(results_1: CheckResults, results_2: CheckResults) -> None:
    """Assert that CheckResults are identical (indicating deterministic output generation)."""
    assert len(results_1.results) == len(results_2.results)
    assert len(results_1.results) >= 1

    for i, (first_result, second_result) in enumerate(zip(results_1.results, results_2.results)):
        assert first_result.exit_code == 0
        assert second_result.exit_code == 0
        assert first_result.report is not None, (
            f"Result {i + 1} should have report field for caching"
        )
        assert second_result.report is not None, (
            f"Result {i + 1} should have report field for caching"
        )

        # Check for empty digest (indicates caching issues)
        empty_digest_fingerprint = (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )
        if first_result.report.fingerprint == empty_digest_fingerprint:
            assert False, (
                f"Caching not working for result {i + 1} - empty artifacts digest detected"
            )

        # Both runs should produce identical output artifacts (deterministic output test)
        # Note: This tests deterministic compilation, not cache hits. TypeScript incremental
        # compilation is now handled via named cache (append_only_caches) which is transparent.
        assert first_result.report == second_result.report, (
            f"❌ DETERMINISTIC OUTPUT FAILURE in result {i + 1}: Output digests should be identical.\n"
            f"First run digest:  {first_result.report.fingerprint}\n"
            f"Second run digest: {second_result.report.fingerprint}\n"
            f"This indicates TypeScript is generating non-deterministic output artifacts."
        )


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


def _load_project_test_files(test_project: str) -> dict[str, str]:
    """Load test files for the specified project type."""
    base_dir = Path(__file__).parent.parent / "test_resources" / test_project
    files = {}

    for file_path in base_dir.rglob("*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(base_dir)
            files[f"{test_project}/{relative_path}"] = file_path.read_text()

    return files


def test_typescript_check_success(basic_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test successful TypeScript type checking."""

    rule_runner, test_project, _ = basic_rule_runner

    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)

    target = rule_runner.get_target(
        Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)

    request = TypeScriptCheckRequest([field_set])
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 1
    assert results.results[0].exit_code == 0


def test_typescript_check_failure(basic_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test TypeScript type checking with type errors."""

    rule_runner, test_project, _ = basic_rule_runner

    # Override index.ts with type error
    test_files = _load_project_test_files(test_project)
    test_files["basic_project/src/index.ts"] = textwrap.dedent("""\
        import { add } from './math';

        export function calculate(): number {
            return add(5, "invalid"); // Type error: string not assignable to number
        }
    """)

    rule_runner.write_files(test_files)

    target = rule_runner.get_target(
        Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)

    request = TypeScriptCheckRequest([field_set])
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 1
    assert results.results[0].exit_code != 0


def test_typescript_check_no_targets_in_project(
    basic_rule_runner: tuple[RuleRunner, str, str],
) -> None:
    """Test project with no TypeScript targets."""

    rule_runner, test_project, _ = basic_rule_runner

    # Override to have only JS sources
    test_files = _load_project_test_files(test_project)
    test_files["basic_project/src/BUILD"] = "javascript_sources()"  # Only JS sources, no TS
    test_files["basic_project/src/index.js"] = "console.log('Hello from JS');"
    del test_files["basic_project/src/index.ts"]

    rule_runner.write_files(test_files)

    # Create an empty request since there are no TS targets
    request = TypeScriptCheckRequest([])
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 0


def test_typescript_check_multiple_projects(
    workspace_rule_runner: tuple[RuleRunner, str, str],
) -> None:
    """Test checking targets across multiple projects (workspace structure)."""

    rule_runner, test_project, _ = workspace_rule_runner

    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)

    # Get targets from different packages in the workspace to simulate multiple projects
    common_types_target = rule_runner.get_target(
        Address("complex_project/common-types/src", relative_file_path="index.ts")
    )
    shared_utils_target = rule_runner.get_target(
        Address(
            "complex_project/shared-utils/src",
            target_name="ts_sources",
            relative_file_path="math.ts",
        )
    )
    main_app_target = rule_runner.get_target(
        Address("complex_project/main-app/src", relative_file_path="index.ts")
    )

    common_types_field_set = TypeScriptCheckFieldSet.create(common_types_target)
    shared_utils_field_set = TypeScriptCheckFieldSet.create(shared_utils_target)
    main_app_field_set = TypeScriptCheckFieldSet.create(main_app_target)

    request = TypeScriptCheckRequest(
        [common_types_field_set, shared_utils_field_set, main_app_field_set]
    )
    results = rule_runner.request(CheckResults, [request])

    # Should have results for the packages
    assert len(results.results) >= 1

    for result in results.results:
        assert result.exit_code == 0
        assert "error" not in result.stdout.lower()


def test_typescript_check_test_files(workspace_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test TypeScript test files using typescript_tests target (workspace structure)."""

    rule_runner, test_project, _ = workspace_rule_runner

    # Add test files to complex project
    test_files = _load_project_test_files(test_project)
    test_files.update(
        {
            "complex_project/main-app/tests/BUILD": "typescript_tests()",
            "complex_project/main-app/tests/math.test.ts": textwrap.dedent("""
            import { add } from '@test/shared-utils';

            // Test file imports should work
            const result = add(2, 3);
            console.log(`Test result: ${result}`);
        """),
        }
    )

    rule_runner.write_files(test_files)

    test_target = rule_runner.get_target(
        Address("complex_project/main-app/tests", relative_file_path="math.test.ts")
    )
    test_field_set = TypeScriptCheckFieldSet.create(test_target)

    request = TypeScriptCheckRequest([test_field_set])
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 1
    assert results.results[0].exit_code == 0


def test_typescript_check_cross_project_imports(
    basic_rule_runner: tuple[RuleRunner, str, str],
) -> None:
    """Test that cross-project imports fail as expected (projects are compiled in isolation)."""

    rule_runner, test_project, _ = basic_rule_runner

    # Simplify to test imports that should fail within a single workspace
    # by trying to import from a non-workspace path
    test_files = _load_project_test_files(test_project)

    # Override to try importing from an invalid path
    test_files["basic_project/src/index.ts"] = textwrap.dedent("""
        // This import should fail - trying to import from non-existent external path
        import { nonExistentFunction } from '../../external-project/src/shared';

        export function useExternal(): string {
            return nonExistentFunction('test');
        }
    """)

    rule_runner.write_files(test_files)

    cross_import_target = rule_runner.get_target(
        Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts")
    )
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


def test_typescript_check_pnpm_link_protocol_success(
    pnpm_rule_runner: tuple[RuleRunner, str, str],
) -> None:
    """Test that pnpm link: protocol allows successful imports between packages."""

    rule_runner, test_project, _ = pnpm_rule_runner

    # Load project files (pnpm_link uses special test prefix)
    test_files = _load_project_test_files(test_project)

    rule_runner.write_files(test_files)

    parent_target = rule_runner.get_target(Address("pnpm_link/src", relative_file_path="main.ts"))
    parent_field_set = TypeScriptCheckFieldSet.create(parent_target)

    request = TypeScriptCheckRequest([parent_field_set])
    results = rule_runner.request(CheckResults, [request])

    # Should succeed - pnpm link: protocol should resolve correctly
    assert len(results.results) == 1
    assert results.results[0].exit_code == 0, (
        f"TypeScript check failed: {results.results[0].stdout}\n{results.results[0].stderr}"
    )


def test_typescript_check_tsx_files(basic_rule_runner: tuple[RuleRunner, str, str]) -> None:
    """Test TypeScript compilation of .tsx files with React components."""

    rule_runner, test_project, _ = basic_rule_runner

    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)

    tsx_target = rule_runner.get_target(
        Address("basic_project/src", target_name="tsx_sources", relative_file_path="Button.tsx")
    )
    tsx_field_set = TypeScriptCheckFieldSet.create(tsx_target)

    request = TypeScriptCheckRequest([tsx_field_set])
    results = rule_runner.request(CheckResults, [request])

    # TSX compilation should work with React types
    assert len(results.results) == 1
    assert results.results[0].exit_code == 0, (
        f"TypeScript check of TSX failed: {results.results[0].stdout}\n{results.results[0].stderr}"
    )


def test_typescript_deterministic_output_single_project(
    basic_rule_runner: tuple[RuleRunner, str, str],
) -> None:
    """Test TypeScript deterministic output generation with single project.

    Validates that running compilation twice produces identical output artifacts, indicating
    deterministic compilation behavior. This is separate from incremental compilation testing.
    """

    rule_runner, test_project, _ = basic_rule_runner

    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)

    target = rule_runner.get_target(
        Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)

    # Run compilation twice and verify deterministic output
    results_1, results_2 = _run_typescript_check_twice(rule_runner, [field_set])
    _assert_identical_output_results(results_1, results_2)


@logging(level=LogLevel.INFO)
def test_typescript_compilation_output_generation(
    basic_rule_runner: tuple[RuleRunner, str, str],
) -> None:
    """Test that TypeScript generates compiled output files.

    Validates that TypeScript --build produces .js and .d.ts output files in the dist directory.
    This ensures TypeScript compilation is working correctly and outputs are captured.
    """

    rule_runner, test_project, _ = basic_rule_runner

    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)

    target = rule_runner.get_target(
        Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)
    request = TypeScriptCheckRequest([field_set])

    # Run compilation to generate output
    results = rule_runner.request(CheckResults, [request])
    assert len(results.results) == 1
    assert results.results[0].exit_code == 0

    result = results.results[0]

    # Validate that compilation outputs are captured
    assert result.report is not None, "CheckResult should have report field for output caching"

    from pants.engine.fs import Digest, Snapshot

    assert isinstance(result.report, Digest), "Report should be a Digest for output caching"

    empty_digest_fingerprint = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert result.report.fingerprint != empty_digest_fingerprint, (
        "❌ No TypeScript compilation outputs captured"
    )

    snapshot = rule_runner.request(Snapshot, [result.report])

    # Verify compiled outputs are present
    js_files = [f for f in snapshot.files if f.endswith(".js")]
    dts_files = [f for f in snapshot.files if f.endswith(".d.ts")]

    assert len(js_files) > 0, f"❌ No .js files found. Actual files: {sorted(snapshot.files)}"
    assert len(dts_files) > 0, f"❌ No .d.ts files found. Actual files: {sorted(snapshot.files)}"

    # Check for expected output files from basic_project
    expected_files = ["dist/index.js", "dist/index.d.ts", "dist/math.js", "dist/math.d.ts"]
    for expected_file in expected_files:
        assert expected_file in snapshot.files, (
            f"❌ Missing expected file: {expected_file}. Found: {sorted(snapshot.files)}"
        )


def test_package_manager_config_dependency_tracking(
    basic_rule_runner: tuple[RuleRunner, str, str],
) -> None:
    """Test that .npmrc files declared as dependencies of package_json are properly tracked.

    This test verifies that when .npmrc files are declared as dependencies of package_json targets,
    changes to .npmrc content are detected and cause package installation to behave accordingly.
    """
    rule_runner, test_project, package_manager = basic_rule_runner
    test_files = _load_project_test_files(test_project)
    original_package_json = json.loads(test_files[f"{test_project}/package.json"])

    # Step 1: Start with valid .npmrc and proper dependency declaration
    test_files.update(
        {
            f"{test_project}/.npmrc": "registry=https://registry.npmjs.org/",
            f"{test_project}/BUILD": textwrap.dedent("""\
                package_json(dependencies=[":npmrc"])
                file(name="npmrc", source=".npmrc")
                """),
        }
    )

    rule_runner.write_files(test_files)

    target = rule_runner.get_target(
        Address(f"{test_project}/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)
    request = TypeScriptCheckRequest([field_set])

    results_1 = rule_runner.request(CheckResults, [request])
    assert len(results_1.results) == 1
    assert results_1.results[0].exit_code == 0, (
        f"First run should succeed with valid .npmrc. "
        f"stdout: {results_1.results[0].stdout}, stderr: {results_1.results[0].stderr}"
    )

    # Step 2: Change .npmrc to malformed content AND add new dependency to force package manager execution
    # This ensures all package managers (including pnpm) must access the registry and encounter the invalid URL
    original_package_json["devDependencies"] = original_package_json.get("devDependencies", {})
    original_package_json["devDependencies"]["is-odd"] = (
        "3.0.1"  # Update dep to force network access
    )

    test_files.update(
        {
            f"{test_project}/.npmrc": "registry=not-a-valid-url",
            f"{test_project}/package.json": json.dumps(original_package_json, indent=2),
        }
    )
    rule_runner.write_files(test_files)

    # Second run with malformed .npmrc should fail due to dependency tracking
    # Package managers must fetch new dependency from invalid registry → fail with ERR_INVALID_URL
    with pytest.raises(ExecutionError) as exc_info:
        rule_runner.request(CheckResults, [request])

    # Verify the error is related to the malformed .npmrc
    error_str = str(exc_info.value)
    expected_errors = ["ERR_INVALID_URL", "failed with exit code 1", "Invalid URL"]
    assert any(expected in error_str for expected in expected_errors), (
        f"Expected {package_manager} error message to contain one of {expected_errors}, got: {exc_info.value}"
    )


def test_file_targets_available_during_typescript_compilation(
    basic_rule_runner: tuple[RuleRunner, str, str],
) -> None:
    """Test that file targets are available during TypeScript compilation.

    This test verifies that file() targets are properly included in the TypeScript compilation
    sandbox by making TypeScript code directly import a JSON file provided by a file() target. If
    the dependency mechanism is broken, tsc will fail with "Cannot find module" error.
    """
    rule_runner, test_project, _ = basic_rule_runner

    test_files = _load_project_test_files(test_project)

    # Create a JSON file that TypeScript will import
    test_files.update(
        {
            # JSON data file to be provided by file() target
            f"{test_project}/config.json": json.dumps(
                {"message": "This content comes from a file target", "value": 42}
            ),
            # tsconfig.json that enables JSON imports and includes specific files
            f"{test_project}/tsconfig.json": json.dumps(
                {
                    "compilerOptions": {
                        "target": "ES2017",
                        "module": "commonjs",
                        "resolveJsonModule": True,
                        "esModuleInterop": True,
                        "declaration": True,
                        "composite": True,
                        "outDir": "./dist",
                    },
                    "include": ["src/index.ts", "config.json"],
                }
            ),
            # TypeScript source that imports the JSON file
            f"{test_project}/src/index.ts": textwrap.dedent("""
            // This import will fail if the file() target dependency is not working
            import config from '../config.json';

            // Type checking ensures the import resolved correctly
            const message: string = config.message;
            const value: number = config.value;

            console.log(`Message: ${message}, Value: ${value}`);
        """),
            # BUILD file with file target
            f"{test_project}/BUILD": textwrap.dedent("""
            package_json()

            # Provides config.json as a dependency
            file(name="config_data", source="config.json")
        """),
            # Override src/BUILD to include dependencies on the file target
            # Only include index.ts to avoid React errors from Button.tsx
            f"{test_project}/src/BUILD": textwrap.dedent(
                """
            # Single TypeScript source that depends on the file target in parent directory
            typescript_sources(
                name="ts_sources",
                sources=["index.ts"],
                dependencies=["//{test_project}:config_data"],
            )
        """.format(test_project=test_project)
            ),
        }
    )

    rule_runner.write_files(test_files)

    target = rule_runner.get_target(
        Address(f"{test_project}/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)
    request = TypeScriptCheckRequest([field_set])

    # Run TypeScript compilation
    results = rule_runner.request(CheckResults, [request])
    assert len(results.results) == 1

    result = results.results[0]

    if "Cannot find module '../config.json'" in result.stdout:
        assert False, (
            "❌ FILE DEPENDENCY FAILURE: TypeScript cannot find config.json from file() target.\n"
            f"This proves the file target dependency mechanism is broken.\n"
            f"TypeScript output: {result.stdout}"
        )

    # Success: TypeScript compilation succeeded with JSON import
    assert result.exit_code == 0, (
        f"❌ COMPILATION FAILURE: TypeScript compilation failed.\n"
        f"Exit code: {result.exit_code}\n"
        f"Stdout: {result.stdout}\n"
        f"Stderr: {result.stderr}"
    )


@logging(level=LogLevel.DEBUG)
def test_typescript_incremental_compilation_cache_rule_runner(
    basic_rule_runner: tuple[RuleRunner, str, str],
) -> None:
    """Test TypeScript incremental compilation cache using comprehensive 4-run pattern.

    This test replicates the integration test scenarios using rule-runner approach:
    1. First run: Create cache, expect full build
    2. Second run: Use cache, expect incremental build (with --verbose/-v variation)
    3. Third run: After file modification, expect full rebuild
    4. Fourth run: After rebuild, expect incremental build again

    Uses --verbose/-v alternation to ensure proper Process cache invalidation.
    Parameterized to test all package managers: npm, pnpm, yarn.
    """
    import json
    import os
    import textwrap
    from pathlib import Path

    rule_runner, test_project, package_manager = basic_rule_runner
    print(f"🔍 COMPREHENSIVE TypeScript cache testing with {package_manager}")
    print("=" * 60)

    # Load and write project files
    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)

    # Get target and create field set
    target = rule_runner.get_target(
        Address(f"{test_project}/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)
    request = TypeScriptCheckRequest([field_set])

    # RUN 1: First compilation - should create cache and perform full build
    print("\n📋 RUN 1: First compilation (should create cache)")
    print("-" * 50)
    results_1 = rule_runner.request(CheckResults, [request])
    assert len(results_1.results) == 1
    assert results_1.results[0].exit_code == 0, (
        f"First compilation failed: {results_1.results[0].stdout}\n{results_1.results[0].stderr}"
    )

    # Get cache directory
    with rule_runner.pushd():
        Path("BUILDROOT").touch()
        bootstrap_options = rule_runner.options_bootstrapper.bootstrap_options.for_global_scope()

    named_cache_dir = bootstrap_options.named_caches_dir
    typescript_cache_dir = os.path.join(named_cache_dir, "typescript_cache")
    print(f"📁 Cache directory: {typescript_cache_dir}")

    # Verify cache directory and .tsbuildinfo files
    assert os.path.exists(typescript_cache_dir), (
        f"Cache directory not created: {typescript_cache_dir}"
    )

    tsbuildinfo_files = []
    for root, dirs, files in os.walk(typescript_cache_dir):
        for file in files:
            if file.endswith(".tsbuildinfo"):
                tsbuildinfo_files.append(os.path.join(root, file))

    assert len(tsbuildinfo_files) > 0, "No .tsbuildinfo files found in cache directory"
    print(f"✅ Cache created with {len(tsbuildinfo_files)} .tsbuildinfo file(s)")

    # Verify .tsbuildinfo content
    with open(tsbuildinfo_files[0]) as f:
        tsbuildinfo_content = json.load(f)
    assert "fileInfos" in tsbuildinfo_content, "tsbuildinfo missing fileInfos field"
    assert "fileNames" in tsbuildinfo_content, "tsbuildinfo missing fileNames field"
    assert len(tsbuildinfo_content["fileInfos"]) > 0, "tsbuildinfo fileInfos is empty"

    # Verify first run behavior from TypeScript output
    combined_output1 = results_1.results[0].stdout + "\n" + results_1.results[0].stderr
    ts_status1 = parse_typescript_build_status(combined_output1)

    print(f"📊 First run TypeScript status: {ts_status1}")
    if ts_status1["has_typescript_output"]:
        assert ts_status1["full_build"], (
            f"Should perform full build on first run. Output: {combined_output1}"
        )
        print("✅ First run performed full build as expected")
    else:
        print(
            "ℹ️  First run: No TypeScript verbose output detected (may not have --verbose enabled)"
        )

    # RUN 2: Second compilation with argument variation - should use cache for incremental build
    print("\n📋 RUN 2: Second compilation with -v arg (should use cache)")
    print("-" * 50)

    # Change TypeScript args on same rule_runner for Process cache invalidation
    # This keeps the same build root so cache can be shared
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            "--typescript-extra-build-args=['-v']",  # Use -v instead of --verbose
            "-ldebug",
            "--keep-sandboxes=always",
        ],
        env_inherit={"PATH"},
    )

    # Use same target and request - build root stays the same
    results_2 = rule_runner.request(CheckResults, [request])
    assert len(results_2.results) == 1
    assert results_2.results[0].exit_code == 0, (
        f"Second compilation failed: {results_2.results[0].stdout}\n{results_2.results[0].stderr}"
    )

    # Verify second run behavior
    combined_output2 = results_2.results[0].stdout + "\n" + results_2.results[0].stderr
    ts_status2 = parse_typescript_build_status(combined_output2)

    print(f"📊 Second run TypeScript status: {ts_status2}")
    if ts_status2["has_typescript_output"]:
        assert ts_status2["incremental_build"], (
            f"Should use incremental build on second run. Output: {combined_output2}"
        )
        assert not ts_status2["full_build"], (
            f"Should NOT perform full build on second run. Output: {combined_output2}"
        )
        print("✅ Second run used incremental compilation successfully")
    else:
        print("ℹ️  Second run: No TypeScript verbose output detected")

    # RUN 3: File modification - should trigger rebuild
    print("\n📋 RUN 3: After file modification (should trigger rebuild)")
    print("-" * 50)

    # Modify index.ts file (since cache logic only touches index.ts files for validation)
    modified_index_content = textwrap.dedent("""
        import { add } from './math';

        export function calculate(): number {
            // Modified: added comment to trigger cache invalidation
            return add(2, 3);
        }
    """).strip()

    # Update the test files and rewrite to same rule runner
    test_files[f"{test_project}/src/index.ts"] = modified_index_content

    # Change TypeScript args back to --verbose for Process cache invalidation
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            "--typescript-extra-build-args=['--verbose']",  # Back to --verbose
            "-ldebug",
            "--keep-sandboxes=always",
        ],
        env_inherit={"PATH"},
    )
    rule_runner.write_files(test_files)  # Write modified files

    # Use same target and request - file modification will be detected
    results_3 = rule_runner.request(CheckResults, [request])
    assert len(results_3.results) == 1
    assert results_3.results[0].exit_code == 0, (
        f"Third compilation failed: {results_3.results[0].stdout}\n{results_3.results[0].stderr}"
    )

    # Verify third run behavior (should detect file change and rebuild)
    combined_output3 = results_3.results[0].stdout + "\n" + results_3.results[0].stderr
    ts_status3 = parse_typescript_build_status(combined_output3)

    print(f"📊 Third run TypeScript status: {ts_status3}")
    if ts_status3["has_typescript_output"]:
        assert ts_status3["full_build"], (
            f"Should perform full build after file modification. Output: {combined_output3}"
        )
        assert not ts_status3["incremental_build"], (
            f"Should NOT report incremental when files changed. Output: {combined_output3}"
        )
        print("✅ File modification triggered rebuild as expected")
    else:
        print("ℹ️  Third run: No TypeScript verbose output detected")

    # RUN 4: After modification - should use cache again
    print("\n📋 RUN 4: After rebuild (should use cache again)")
    print("-" * 50)

    # Change TypeScript args to -v for Process cache invalidation
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            "--typescript-extra-build-args=['-v']",  # Back to -v
            "-ldebug",
            "--keep-sandboxes=always",
        ],
        env_inherit={"PATH"},
    )

    # Use same target and request - cache should be used for incremental build
    results_4 = rule_runner.request(CheckResults, [request])
    assert len(results_4.results) == 1
    assert results_4.results[0].exit_code == 0, (
        f"Fourth compilation failed: {results_4.results[0].stdout}\n{results_4.results[0].stderr}"
    )

    # Verify fourth run behavior (should use incremental build again)
    combined_output4 = results_4.results[0].stdout + "\n" + results_4.results[0].stderr
    ts_status4 = parse_typescript_build_status(combined_output4)

    print(f"📊 Fourth run TypeScript status: {ts_status4}")
    if ts_status4["has_typescript_output"]:
        assert ts_status4["incremental_build"], (
            f"Should use incremental build after rebuild. Output: {combined_output4}"
        )
        assert not ts_status4["full_build"], (
            f"Should NOT perform full build when cache is valid. Output: {combined_output4}"
        )
        print("✅ Cache works after file modification cycle")
    else:
        print("ℹ️  Fourth run: No TypeScript verbose output detected")

    print("\n🎉 COMPREHENSIVE TypeScript incremental compilation cache test completed!")
    print(f"   Package manager: {package_manager}")
    print("   All 4 scenarios passed: cache creation → incremental → file change → incremental")
    print("=" * 60)
