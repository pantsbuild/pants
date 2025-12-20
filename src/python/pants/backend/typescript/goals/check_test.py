# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import os
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
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner

JS_TYPE_ERROR_FILE_NUMBER_TO_STRING = (
    'let x = "hello";\nx = 42; // Type error: cannot assign number to string\n'
)

TestProjectAndPackageManager = tuple[str, str]
RuleRunnerWithProjectAndPackageManager = tuple[RuleRunner, str, str]


@pytest.fixture(
    params=[("basic_project", "npm"), ("basic_project", "pnpm"), ("basic_project", "yarn")]
)
def basic_project_test(request) -> TestProjectAndPackageManager:
    return cast(TestProjectAndPackageManager, request.param)


@pytest.fixture(params=[("complex_project", "npm"), ("complex_project", "yarn")])
def complex_project_test(request) -> TestProjectAndPackageManager:
    return cast(TestProjectAndPackageManager, request.param)


@pytest.fixture(params=[("pnpm_link", "pnpm")])
def pnpm_project_test(request) -> TestProjectAndPackageManager:
    return cast(TestProjectAndPackageManager, request.param)


def _create_rule_runner(package_manager: str) -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
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
        [f"--nodejs-package-manager={package_manager}"],
        env_inherit={"PATH"},
    )
    return rule_runner


@pytest.fixture
def basic_rule_runner(
    basic_project_test: TestProjectAndPackageManager,
) -> RuleRunnerWithProjectAndPackageManager:
    test_project, package_manager = basic_project_test
    return _create_rule_runner(package_manager), test_project, package_manager


@pytest.fixture
def complex_proj_rule_runner(
    complex_project_test: TestProjectAndPackageManager,
) -> RuleRunnerWithProjectAndPackageManager:
    test_project, package_manager = complex_project_test
    return _create_rule_runner(package_manager), test_project, package_manager


@pytest.fixture
def pnpm_rule_runner(
    pnpm_project_test: TestProjectAndPackageManager,
) -> RuleRunnerWithProjectAndPackageManager:
    test_project, package_manager = pnpm_project_test
    return _create_rule_runner(package_manager), test_project, package_manager


def _parse_typescript_build_status(stdout: str) -> str:
    if (
        "is up to date but needs to update timestamps of output files that are older than input files"
        in stdout
    ):
        return "incremental_build"
    elif "Building project '" in stdout:
        return "full_build"
    else:
        return "no_verbose_output"


def _load_project_test_files(test_project: str) -> dict[str, str]:
    base_dir = Path(__file__).parent.parent / "test_resources" / test_project
    files = {}

    for file_path in base_dir.rglob("*"):
        if file_path.is_file():
            relative_path = file_path.relative_to(base_dir)
            files[f"{test_project}/{relative_path}"] = file_path.read_text()

    return files


def _override_index_ts_with_TS2345_error() -> str:
    return textwrap.dedent("""\
        import { add } from './math';

        export function calculate(): number {
            return add(5, "invalid"); // Type error: string not assignable to number
        }
    """)


def _override_math_ts_with_TS2322_error() -> str:
    return textwrap.dedent("""\
        export function add(a: number, b: number): number {
            return "not a number"; // This should cause TS2322 error
        }
    """)


def test_typescript_check_success(
    basic_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
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


def test_typescript_check_failure(
    basic_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
    rule_runner, test_project, _ = basic_rule_runner

    test_files = _load_project_test_files(test_project)
    test_files["basic_project/src/index.ts"] = _override_index_ts_with_TS2345_error()
    rule_runner.write_files(test_files)

    target = rule_runner.get_target(
        Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)
    request = TypeScriptCheckRequest([field_set])
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 1
    result = results.results[0]
    assert result.exit_code != 0

    error_output = result.stdout + result.stderr
    assert "TS2345" in error_output
    assert "not assignable to parameter of type 'number'" in error_output


def test_typescript_check_fails_when_package_dep_fails(
    complex_proj_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
    rule_runner, test_project, _ = complex_proj_rule_runner
    test_files = _load_project_test_files(test_project)

    test_files["complex_project/shared-utils/src/math.ts"] = _override_math_ts_with_TS2322_error()
    rule_runner.write_files(test_files)

    # Target main-app package but error is in shared-utils dependency
    main_target = rule_runner.get_target(
        Address("complex_project/main-app/src", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(main_target)

    request = TypeScriptCheckRequest([field_set])
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 1
    result = results.results[0]
    assert result.exit_code != 0, "Should fail due to type error in project dependency"

    error_output = result.stdout + result.stderr
    assert "TS2322" in error_output
    assert "not assignable to type 'number'" in error_output
    assert "shared-utils/src/math.ts" in error_output


def test_typescript_check_missing_outdir_validation(
    basic_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
    rule_runner, test_project, _ = basic_rule_runner

    test_files = _load_project_test_files(test_project)
    tsconfig_content = json.loads(test_files[f"{test_project}/tsconfig.json"])
    if "compilerOptions" in tsconfig_content and "outDir" in tsconfig_content["compilerOptions"]:
        del tsconfig_content["compilerOptions"]["outDir"]
    test_files[f"{test_project}/tsconfig.json"] = json.dumps(tsconfig_content, indent=2)
    rule_runner.write_files(test_files)

    target = rule_runner.get_target(
        Address(f"{test_project}/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)
    request = TypeScriptCheckRequest([field_set])

    with pytest.raises(Exception) as exc_info:
        rule_runner.request(CheckResults, [request])
    error_message = str(exc_info.value)
    assert "missing required 'outDir' setting" in error_message
    assert "TypeScript type-checking requires an explicit outDir" in error_message


def test_typescript_check_multiple_projects(
    basic_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
    rule_runner, _, _ = basic_rule_runner

    basic_project_files = _load_project_test_files("basic_project")
    test_files = {}

    # Project A - Independent project with its own package.json and tsconfig.json
    for file_path, content in basic_project_files.items():
        new_path = file_path.replace("basic_project", "project-a")
        if "package.json" in file_path:
            pkg_data = json.loads(content)
            pkg_data["name"] = "project-a"
            pkg_data["description"] = "Independent TypeScript project A"
            test_files[new_path] = json.dumps(pkg_data, indent=2)
        elif "index.ts" in file_path:
            test_files[new_path] = textwrap.dedent("""
                import { add } from './math';

                export function calculateA(): number {
                    return add(10, 20); // Project A calculation
                }
            """).strip()
        else:
            test_files[new_path] = content

    # Project B - Independent project with its own package.json and tsconfig.json
    for file_path, content in basic_project_files.items():
        new_path = file_path.replace("basic_project", "project-b")
        if "package.json" in file_path:
            pkg_data = json.loads(content)
            pkg_data["name"] = "project-b"
            pkg_data["description"] = "Independent TypeScript project B"
            test_files[new_path] = json.dumps(pkg_data, indent=2)
        elif "index.ts" in file_path:
            test_files[new_path] = textwrap.dedent("""
                import { add } from './math';

                export function calculateB(): number {
                    return add(5, 15); // Project B calculation
                }
            """).strip()
        else:
            test_files[new_path] = content

    rule_runner.write_files(test_files)

    project_a_target = rule_runner.get_target(
        Address("project-a/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    project_b_target = rule_runner.get_target(
        Address("project-b/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    project_a_field_set = TypeScriptCheckFieldSet.create(project_a_target)
    project_b_field_set = TypeScriptCheckFieldSet.create(project_b_target)

    request = TypeScriptCheckRequest([project_a_field_set, project_b_field_set])
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 2, f"Expected 2 projects, got {len(results.results)}"
    assert all(result.exit_code == 0 for result in results.results), (
        f"TypeScript compilation failed for projects: {[r.exit_code for r in results.results]}"
    )


def test_typescript_check_pnpm_link_protocol_success(
    pnpm_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
    rule_runner, test_project, _ = pnpm_rule_runner
    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)
    parent_target = rule_runner.get_target(Address("pnpm_link/src", relative_file_path="main.ts"))
    parent_field_set = TypeScriptCheckFieldSet.create(parent_target)

    request = TypeScriptCheckRequest([parent_field_set])
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 1
    assert results.results[0].exit_code == 0, (
        f"TypeScript check failed: {results.results[0].stdout}\n{results.results[0].stderr}"
    )


def test_file_targets_available_during_typescript_compilation(
    basic_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
    rule_runner, test_project, _ = basic_rule_runner

    test_files = _load_project_test_files(test_project)
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
                f"""
            # Single TypeScript source that depends on the file target in parent directory
            typescript_sources(
                name="ts_sources",
                sources=["index.ts"],
                dependencies=["//{test_project}:config_data"],
            )
        """
            ),
        }
    )
    rule_runner.write_files(test_files)
    target = rule_runner.get_target(
        Address(f"{test_project}/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)
    request = TypeScriptCheckRequest([field_set])

    results = rule_runner.request(CheckResults, [request])
    assert len(results.results) == 1

    result = results.results[0]
    assert result.exit_code == 0, f"TypeScript compilation failed: {result.stdout}"
    assert "Cannot find module '../config.json'" not in result.stdout, (
        "File target dependency not working - TypeScript cannot find config.json"
    )


def test_typescript_incremental_compilation_cache(
    basic_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
    """Test TypeScript incremental compilation cache using comprehensive 4-run pattern.

    This test replicates the integration test scenarios using rule-runner approach:
    1. First run: Create cache, expect full build
    2. Second run: Use cache, expect incremental build (with --verbose/-v variation)
    3. Third run: After file modification, expect full rebuild
    4. Fourth run: After rebuild, expect incremental build again

    Uses --verbose/-v alternation to ensure Process cache invalidation.
    """
    rule_runner, test_project, package_manager = basic_rule_runner

    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)
    target = rule_runner.get_target(
        Address(f"{test_project}/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    field_set = TypeScriptCheckFieldSet.create(target)
    request = TypeScriptCheckRequest([field_set])

    # RUN 1: First compilation - should create cache and perform full build
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            "--typescript-extra-build-args=['--verbose']",
        ],
        env_inherit={"PATH"},
    )
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
    typescript_cache_dir = os.path.join(str(named_cache_dir), "typescript_cache")

    # Verify cache directory and .tsbuildinfo files
    assert os.path.exists(typescript_cache_dir), (
        f"Cache directory not created: {typescript_cache_dir}"
    )
    tsbuildinfo_files = []
    for root, _, files in os.walk(typescript_cache_dir):
        for file in files:
            if file.endswith(".tsbuildinfo"):
                tsbuildinfo_files.append(os.path.join(root, file))

    assert len(tsbuildinfo_files) > 0, "No .tsbuildinfo files found in cache directory"

    # Verify first run behavior from TypeScript output
    combined_output1 = results_1.results[0].stdout + "\n" + results_1.results[0].stderr
    ts_status1 = _parse_typescript_build_status(combined_output1)
    assert ts_status1 == "full_build", (
        f"Expected full_build on first run, got: {ts_status1}. Output: {combined_output1}"
    )

    # RUN 2: Second compilation with argument variation - should use cache for incremental build

    # Change TypeScript args on same rule_runner for Process cache invalidation
    # This keeps the same build root so cache can be reused
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            "--typescript-extra-build-args=['-v']",  # Use -v instead of --verbose
        ],
        env_inherit={"PATH"},
    )

    results_2 = rule_runner.request(CheckResults, [request])
    assert len(results_2.results) == 1
    assert results_2.results[0].exit_code == 0, (
        f"Second compilation failed: {results_2.results[0].stdout}\n{results_2.results[0].stderr}"
    )

    combined_output2 = results_2.results[0].stdout + "\n" + results_2.results[0].stderr
    ts_status2 = _parse_typescript_build_status(combined_output2)
    assert ts_status2 == "incremental_build", (
        f"Expected incremental_build on second run, got: {ts_status2}. Output: {combined_output2}"
    )

    # RUN 3: File modification - should trigger rebuild
    modified_index_content = textwrap.dedent("""
        import { add } from './math';

        export function calculate(): number {
            // Modified: added comment to trigger cache invalidation
            return add(2, 3);
        }
    """).strip()
    test_files[f"{test_project}/src/index.ts"] = modified_index_content

    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            "--typescript-extra-build-args=['--verbose']",  # Back to --verbose
        ],
        env_inherit={"PATH"},
    )
    rule_runner.write_files(test_files)  # Write modified files
    results_3 = rule_runner.request(CheckResults, [request])

    assert len(results_3.results) == 1
    assert results_3.results[0].exit_code == 0, (
        f"Third compilation failed: {results_3.results[0].stdout}\n{results_3.results[0].stderr}"
    )
    combined_output3 = results_3.results[0].stdout + "\n" + results_3.results[0].stderr
    ts_status3 = _parse_typescript_build_status(combined_output3)
    assert ts_status3 == "full_build", (
        f"Expected full_build after file modification, got: {ts_status3}. Output: {combined_output3}"
    )

    # RUN 4: After modification - should use cache again
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            "--typescript-extra-build-args=['-v']",  # Back to -v
        ],
        env_inherit={"PATH"},
    )

    results_4 = rule_runner.request(CheckResults, [request])

    assert len(results_4.results) == 1
    assert results_4.results[0].exit_code == 0, (
        f"Fourth compilation failed: {results_4.results[0].stdout}\n{results_4.results[0].stderr}"
    )
    combined_output4 = results_4.results[0].stdout + "\n" + results_4.results[0].stderr
    ts_status4 = _parse_typescript_build_status(combined_output4)
    assert ts_status4 == "incremental_build", (
        f"Expected incremental_build after rebuild, got: {ts_status4}. Output: {combined_output4}"
    )


def test_setting_typescript_version_emits_warning(
    basic_rule_runner: RuleRunnerWithProjectAndPackageManager, caplog
) -> None:
    rule_runner, test_project, package_manager = basic_rule_runner
    test_files = _load_project_test_files(test_project)
    rule_runner.write_files(test_files)

    rule_runner.set_options(
        [f"--nodejs-package-manager={package_manager}", "--typescript-version=typescript@5.0.0"],
        env_inherit={"PATH"},
    )

    target = rule_runner.get_target(
        Address("basic_project/src", target_name="ts_sources", relative_file_path="index.ts")
    )
    request = TypeScriptCheckRequest(field_sets=(TypeScriptCheckFieldSet.create(target),))
    rule_runner.request(CheckResults, [request])

    assert caplog.records
    assert "You set --typescript-version=typescript@5.0.0" in caplog.text
    assert "This setting is ignored because TypeScript always uses" in caplog.text


def test_check_javascript_enabled_via_tsconfig(
    basic_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
    rule_runner, test_project, _ = basic_rule_runner
    test_files = _load_project_test_files(test_project)

    tsconfig_content = json.loads(test_files["basic_project/tsconfig.json"])
    tsconfig_content["compilerOptions"]["allowJs"] = True
    tsconfig_content["compilerOptions"]["checkJs"] = True
    test_files["basic_project/tsconfig.json"] = json.dumps(tsconfig_content, indent=2)

    test_files["basic_project/src/error.js"] = JS_TYPE_ERROR_FILE_NUMBER_TO_STRING
    test_files["basic_project/src/BUILD"] = (
        'javascript_sources(name="js_sources")\ntypescript_sources()\n'
    )

    rule_runner.write_files(test_files)

    js_target = rule_runner.get_target(
        Address("basic_project/src", target_name="js_sources", relative_file_path="error.js")
    )
    request = TypeScriptCheckRequest(field_sets=(TypeScriptCheckFieldSet.create(js_target),))
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 1
    assert results.results[0].exit_code != 0
    assert "error.js" in results.results[0].stdout
    assert "Type 'number' is not assignable to type 'string'" in results.results[0].stdout


def test_check_javascript_disabled_via_tsconfig(
    basic_rule_runner: RuleRunnerWithProjectAndPackageManager,
) -> None:
    rule_runner, test_project, _ = basic_rule_runner
    test_files = _load_project_test_files(test_project)

    # Use the same JS file with type error that would be caught if processed
    test_files["basic_project/src/error.js"] = JS_TYPE_ERROR_FILE_NUMBER_TO_STRING
    test_files["basic_project/src/BUILD"] = (
        'javascript_sources(name="js_sources")\ntypescript_sources()\n'
    )

    rule_runner.write_files(test_files)

    js_target = rule_runner.get_target(
        Address("basic_project/src", target_name="js_sources", relative_file_path="error.js")
    )
    request = TypeScriptCheckRequest(field_sets=(TypeScriptCheckFieldSet.create(js_target),))
    results = rule_runner.request(CheckResults, [request])

    assert len(results.results) == 1
    assert results.results[0].exit_code == 0
    assert "error.js" not in results.results[0].stdout
