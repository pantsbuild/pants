# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import cast

import pytest

from pants.backend.javascript import package_json
from pants.backend.javascript.goals import test
from pants.backend.javascript.goals.test import (
    JSCoverageData,
    JSTestFieldSet,
    JSTestRequest,
    TestMetadata,
)
from pants.backend.javascript.package_json import PackageJsonTarget
from pants.backend.javascript.target_types import (
    JSSourcesGeneratorTarget,
    JSTestsGeneratorTarget,
    JSTestTarget,
)
from pants.backend.javascript.testutil import load_js_test_project
from pants.backend.tsx.target_types import (
    TSXSourcesGeneratorTarget,
    TSXTestsGeneratorTarget,
    TSXTestTarget,
)
from pants.backend.typescript.target_types import (
    TypeScriptSourcesGeneratorTarget,
    TypeScriptTestsGeneratorTarget,
    TypeScriptTestTarget,
)
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult, get_filtered_environment
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner

ATTEMPTS_DEFAULT_OPTION = 2


@pytest.fixture(params=["npm", "pnpm", "yarn"])
def package_manager(request) -> str:
    return cast(str, request.param)


@pytest.fixture
def rule_runner(package_manager: str) -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *test.rules(),
            get_filtered_environment,
            QueryRule(TestResult, [JSTestRequest.Batch]),
        ],
        target_types=[
            PackageJsonTarget,
            JSSourcesGeneratorTarget,
            JSTestsGeneratorTarget,
            JSTestTarget,
            TypeScriptSourcesGeneratorTarget,
            TypeScriptTestsGeneratorTarget,
            TypeScriptTestTarget,
            TSXSourcesGeneratorTarget,
            TSXTestsGeneratorTarget,
            TSXTestTarget,
        ],
        objects=dict(package_json.build_file_aliases().objects),
    )
    rule_runner.set_options(
        [
            f"--nodejs-package-manager={package_manager}",
            f"--test-attempts-default={ATTEMPTS_DEFAULT_OPTION}",
        ],
        env_inherit={"PATH"},
    )
    return rule_runner


@pytest.fixture
def jest_dev_dependencies() -> dict[str, str]:
    return {"@types/jest": "30.0.0", "jest": "30.2.0", "ts-jest": "29.4.5", "typescript": "5.9.3"}


def make_source_to_test(passing: bool = True):
    operation = "+" if passing else "-"

    return textwrap.dedent(
        f"""\
        export function add(x, y) {{
          return x {operation} y
        }}
        """
    )


def given_package_json(
    *,
    test_script: dict[str, str],
    dev_dependencies: dict[str, str],
    **kwargs,
) -> str:
    return json.dumps(
        {
            "name": "pkg",
            "version": "0.0.1",
            "type": "module",
            "scripts": {**test_script},
            "devDependencies": dev_dependencies,
            "main": "./src/index.mjs",
            **kwargs,
        }
    )


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "test_script, package_json_target",
    [
        pytest.param(
            {"test": "NODE_OPTIONS=--experimental-vm-modules jest"}, "package_json()", id="default"
        ),
        pytest.param(
            {"jest-test": "NODE_OPTIONS=--experimental-vm-modules jest"},
            textwrap.dedent(
                """\
                package_json(scripts=[node_test_script(entry_point="jest-test")])
                """
            ),
            id="custom_test_script",
        ),
    ],
)
@pytest.mark.parametrize("passing", [True, False])
def test_jest_tests_are_successful(
    rule_runner: RuleRunner,
    test_script: dict[str, str],
    package_json_target: str,
    passing: bool,
    package_manager: str,
    jest_dev_dependencies: dict[str, str],
) -> None:
    test_files = load_js_test_project("jest_project", package_manager=package_manager)
    test_files["jest_project/BUILD"] = package_json_target
    test_files["jest_project/package.json"] = given_package_json(
        test_script=test_script,
        dev_dependencies=jest_dev_dependencies,
    )
    test_files["jest_project/src/index.mjs"] = make_source_to_test(passing)

    rule_runner.write_files(test_files)

    tgt = rule_runner.get_target(
        Address("jest_project/src/tests", relative_file_path="index.test.js")
    )
    package = rule_runner.get_target(Address("jest_project", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt, package=package)])
    if passing:
        assert b"Test Suites: 1 passed, 1 total" in result.stderr_bytes
        assert result.exit_code == 0
    else:
        assert result.exit_code == 1
        assert len(result.process_results) == ATTEMPTS_DEFAULT_OPTION


def test_batched_jest_tests_are_successful(
    rule_runner: RuleRunner,
    package_manager: str,
) -> None:
    test_files = load_js_test_project("jest_project", package_manager=package_manager)
    test_files["jest_project/src/tests/BUILD"] = (
        "javascript_tests(name='tests', batch_compatibility_tag='default')"
    )
    test_files["jest_project/src/tests/another.test.js"] = textwrap.dedent(
        """\
        /**
         * @jest-environment node
         */

        import { expect } from "@jest/globals"

        import { add } from "../index.mjs"

        test('adds 2 + 3 to equal 5', () => {
            expect(add(2, 3)).toBe(5);
        });
        """
    )

    rule_runner.write_files(test_files)

    tgt_1 = rule_runner.get_target(
        Address("jest_project/src/tests", relative_file_path="index.test.js")
    )
    tgt_2 = rule_runner.get_target(
        Address("jest_project/src/tests", relative_file_path="another.test.js")
    )
    package = rule_runner.get_target(Address("jest_project", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt_1, tgt_2, package=package)])
    assert b"Test Suites: 2 passed, 2 total" in result.stderr_bytes
    assert result.exit_code == 0


def test_jest_tests_import_typescript_file(
    rule_runner: RuleRunner,
    package_manager: str,
    jest_dev_dependencies: dict[str, str],
) -> None:
    test_files = load_js_test_project("jest_project", package_manager=package_manager)
    test_files["jest_project/package.json"] = given_package_json(
        test_script={"test": "NODE_OPTIONS=--experimental-vm-modules jest"},
        dev_dependencies=jest_dev_dependencies,
        jest={
            "extensionsToTreatAsEsm": [".ts"],
        },
    )
    test_files["jest_project/src/BUILD"] = "typescript_sources()"
    test_files["jest_project/src/index.ts"] = make_source_to_test()
    test_files["jest_project/src/tests/BUILD"] = (
        "javascript_tests(name='tests', batch_compatibility_tag='default')"
    )
    test_files["jest_project/src/tests/index.test.js"] = textwrap.dedent(
        """\
        /**
         * @jest-environment node
         */

        import { expect } from "@jest/globals"

        import { add } from "../index.ts"

        test('adds 1 + 2 to equal 3', () => {
            expect(add(1, 2)).toBe(3);
        });
        """
    )

    rule_runner.write_files(test_files)

    tgt_1 = rule_runner.get_target(
        Address("jest_project/src/tests", relative_file_path="index.test.js")
    )
    package = rule_runner.get_target(Address("jest_project", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt_1, package=package)])
    assert b"Test Suites: 1 passed, 1 total" in result.stderr_bytes
    assert result.exit_code == 0


@pytest.mark.parametrize("passing", [True, False])
def test_mocha_tests(
    passing: bool,
    package_manager: str,
    rule_runner: RuleRunner,
) -> None:
    test_files = load_js_test_project("mocha_project", package_manager=package_manager)
    test_files["mocha_project/src/index.mjs"] = make_source_to_test(passing)

    rule_runner.write_files(test_files)

    tgt = rule_runner.get_target(
        Address("mocha_project/src/tests", relative_file_path="index.test.mjs")
    )
    package = rule_runner.get_target(Address("mocha_project", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt, package=package)])
    if passing:
        assert b"1 passing" in result.stdout_bytes
        assert result.exit_code == 0
    else:
        assert result.exit_code == 1
        assert len(result.process_results) == ATTEMPTS_DEFAULT_OPTION


def test_jest_test_with_coverage_reporting(
    package_manager: str,
    rule_runner: RuleRunner,
) -> None:
    rule_runner.set_options(
        args=[f"--nodejs-package-manager={package_manager}", "--test-use-coverage", "True"],
        env_inherit={"PATH"},
    )

    test_files = load_js_test_project("jest_project", package_manager=package_manager)
    test_files["jest_project/BUILD"] = textwrap.dedent(
        """\
        package_json(
            scripts=[
                node_test_script(
                    coverage_args=['--coverage', '--coverage-directory=.coverage/'],
                    coverage_output_files=['.coverage/clover.xml'],
                )
            ],
        )
        """
    )

    rule_runner.write_files(test_files)

    tgt = rule_runner.get_target(
        Address("jest_project/src/tests", relative_file_path="index.test.js")
    )
    package = rule_runner.get_target(Address("jest_project", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt, package=package)])
    assert result.coverage_data

    rule_runner.write_digest(cast(JSCoverageData, result.coverage_data).snapshot.digest)
    assert Path(rule_runner.build_root, ".coverage/clover.xml").exists()


def given_request_for(*js_test: Target, package: Target) -> JSTestRequest.Batch:
    return JSTestRequest.Batch(
        "",
        tuple(JSTestFieldSet.create(tgt) for tgt in js_test),
        TestMetadata(tuple(), package),
    )


def test_typescript_test_files(
    rule_runner: RuleRunner,
    package_manager: str,
    jest_dev_dependencies: dict[str, str],
) -> None:
    test_files = load_js_test_project("jest_project", package_manager=package_manager)
    test_files["jest_project/package.json"] = given_package_json(
        test_script={"test": "jest"},
        dev_dependencies=jest_dev_dependencies,
        jest={
            "preset": "ts-jest",
        },
    )
    test_files["jest_project/src/BUILD"] = "typescript_sources()"
    test_files["jest_project/src/index.ts"] = textwrap.dedent(
        """\
        export function add(x: number, y: number): number {
          return x + y;
        }
        """
    )
    test_files["jest_project/src/tests/BUILD"] = "typescript_tests(name='tests')"
    test_files["jest_project/src/tests/index.test.ts"] = textwrap.dedent(
        """\
        import { add } from '../index';

        test('adds 1 + 2 to equal 3', () => {
            expect(add(1, 2)).toBe(3);
        });
        """
    )

    rule_runner.write_files(test_files)

    tgt = rule_runner.get_target(
        Address("jest_project/src/tests", relative_file_path="index.test.ts")
    )
    package = rule_runner.get_target(Address("jest_project", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt, package=package)])
    assert b"Test Suites: 1 passed, 1 total" in result.stderr_bytes
    assert result.exit_code == 0


def test_tsx_test_files(
    rule_runner: RuleRunner,
    package_manager: str,
    jest_dev_dependencies: dict[str, str],
) -> None:
    test_files = load_js_test_project("jest_project", package_manager=package_manager)
    test_files["jest_project/package.json"] = given_package_json(
        test_script={"test": "jest"},
        dev_dependencies=jest_dev_dependencies,
        jest={"preset": "ts-jest", "globals": {"ts-jest": {"tsconfig": {"jsx": "react"}}}},
    )
    test_files["jest_project/tsconfig.json"] = json.dumps({"compilerOptions": {"jsx": "react"}})
    test_files["jest_project/src/BUILD"] = "tsx_sources()"
    test_files["jest_project/src/index.tsx"] = textwrap.dedent(
        """\
        export function add(x: number, y: number): number {
          return x + y;
        }
        """
    )
    test_files["jest_project/src/tests/BUILD"] = "tsx_tests(name='tests')"
    test_files["jest_project/src/tests/index.test.tsx"] = textwrap.dedent(
        """\
        import { add } from '../index';

        test('adds 1 + 2 to equal 3', () => {
            expect(add(1, 2)).toBe(3);
        });
        """
    )

    rule_runner.write_files(test_files)

    tgt = rule_runner.get_target(
        Address("jest_project/src/tests", relative_file_path="index.test.tsx")
    )
    package = rule_runner.get_target(Address("jest_project", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt, package=package)])
    assert b"Test Suites: 1 passed, 1 total" in result.stderr_bytes
    assert result.exit_code == 0
