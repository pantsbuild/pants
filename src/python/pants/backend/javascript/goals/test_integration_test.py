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
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult, get_filtered_environment
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import RuleRunner

ATTEMPTS_DEFAULT_OPTION = 2


@pytest.fixture(params=[("npm", "10.8.1"), ("pnpm", "7.33.7"), ("yarn", "1.22.22")])
def package_manager_and_version(request) -> tuple[str, str]:
    return request.param


@pytest.fixture
def rule_runner(package_manager_and_version: tuple[str, str]) -> RuleRunner:
    package_manager, _ = package_manager_and_version
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


_LOCKFILE_FILE_NAMES = {
    "pnpm": "pnpm-lock.yaml",
    "npm": "package-lock.json",
    "yarn": "yarn.lock",
}


def _find_lockfile_resource(package_manager: str, resource_dir: str) -> dict[str, str]:
    for file in (Path(__file__).parent / resource_dir).iterdir():
        if _LOCKFILE_FILE_NAMES.get(package_manager) == file.name:
            return {file.name: file.read_text()}
    raise AssertionError(
        f"No lockfile for {package_manager} set up in test resouces directory {resource_dir}."
    )


@pytest.fixture
def jest_lockfile(package_manager_and_version: tuple[str, str]) -> dict[str, str]:
    package_manager, _ = package_manager_and_version
    return _find_lockfile_resource(package_manager, "jest_resources")


@pytest.fixture
def mocha_lockfile(package_manager_and_version: tuple[str, str]) -> dict[str, str]:
    package_manager, _ = package_manager_and_version
    return _find_lockfile_resource(package_manager, "mocha_resources")


def make_source_to_test(passing: bool = True):
    operation = "+" if passing else "-"

    return textwrap.dedent(
        f"""\
        export function add(x, y) {{
          return x {operation} y
        }}
        """
    )


def given_package_json(*, test_script: dict[str, str], runner: dict[str, str], package_manager: str, package_manager_version: str) -> str:
    return json.dumps(
        {
            "name": "pkg",
            "version": "0.0.1",
            "type": "module",
            "scripts": {**test_script},
            "devDependencies": runner,
            "packageManager": f"{package_manager}@{package_manager_version}",
            "main": "./src/index.mjs",
        }
    )


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
    package_manager_and_version: tuple[str, str],
    rule_runner: RuleRunner,
    test_script: dict[str, str],
    package_json_target: str,
    passing: bool,
    jest_lockfile: dict[str, str],
) -> None:
    package_manager, package_manager_version = package_manager_and_version
    rule_runner.write_files(
        {
            "foo/BUILD": package_json_target,
            "foo/package.json": given_package_json(
                test_script=test_script,
                package_manager=package_manager,
                package_manager_version=package_manager_version,
                runner={"jest": "^29.7.0"},
            ),
            **{f"foo/{key}": value for key, value in jest_lockfile.items()},
            "foo/src/BUILD": "javascript_sources()",
            "foo/src/index.mjs": make_source_to_test(passing),
            "foo/src/tests/BUILD": "javascript_tests(name='tests')",
            "foo/src/tests/index.test.js": textwrap.dedent(
                """\
                /**
                 * @jest-environment node
                 */

                import { expect } from "@jest/globals"

                import { add } from "../index.mjs"

                test('adds 1 + 2 to equal 3', () => {
                    expect(add(1, 2)).toBe(3);
                });
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo/src/tests", relative_file_path="index.test.js"))
    package = rule_runner.get_target(Address("foo", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt, package=package)])
    if passing:
        assert b"Test Suites: 1 passed, 1 total" in result.stderr_bytes
        assert result.exit_code == 0
    else:
        assert result.exit_code == 1
        assert len(result.process_results) == ATTEMPTS_DEFAULT_OPTION


def test_batched_jest_tests_are_successful(
    package_manager_and_version: tuple[str, str], rule_runner: RuleRunner, jest_lockfile: dict[str, str]
) -> None:
    package_manager, package_manager_version = package_manager_and_version
    rule_runner.write_files(
        {
            "foo/BUILD": "package_json()",
            "foo/package.json": given_package_json(
                test_script={"test": "NODE_OPTIONS=--experimental-vm-modules jest"},
                package_manager=package_manager,
                package_manager_version=package_manager_version,
                runner={"jest": "^29.7.0"},
            ),
            **{f"foo/{key}": value for key, value in jest_lockfile.items()},
            "foo/src/BUILD": "javascript_sources()",
            "foo/src/index.mjs": make_source_to_test(),
            "foo/src/tests/BUILD": "javascript_tests(name='tests', batch_compatibility_tag='default')",
            "foo/src/tests/index.test.js": textwrap.dedent(
                """\
                /**
                 * @jest-environment node
                 */

                import { expect } from "@jest/globals"

                import { add } from "../index.mjs"

                test('adds 1 + 2 to equal 3', () => {
                    expect(add(1, 2)).toBe(3);
                });
                """
            ),
            "foo/src/tests/another.test.js": textwrap.dedent(
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
            ),
        }
    )
    tgt_1 = rule_runner.get_target(Address("foo/src/tests", relative_file_path="index.test.js"))
    tgt_2 = rule_runner.get_target(Address("foo/src/tests", relative_file_path="another.test.js"))
    package = rule_runner.get_target(Address("foo", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt_1, tgt_2, package=package)])
    assert b"Test Suites: 2 passed, 2 total" in result.stderr_bytes
    assert result.exit_code == 0


@pytest.mark.parametrize("passing", [True, False])
def test_mocha_tests(
    passing: bool, mocha_lockfile: dict[str, str], package_manager_and_version: tuple[str, str], rule_runner: RuleRunner
) -> None:
    package_manager, package_manager_version = package_manager_and_version
    rule_runner.write_files(
        {
            "foo/BUILD": "package_json()",
            "foo/package.json": given_package_json(
                test_script={"test": "mocha"},
                package_manager=package_manager,
                package_manager_version=package_manager_version,
                runner={"mocha": "^10.2.0"}
            ),
            **{f"foo/{key}": value for key, value in mocha_lockfile.items()},
            "foo/src/BUILD": "javascript_sources()",
            "foo/src/index.mjs": make_source_to_test(passing),
            "foo/src/tests/BUILD": "javascript_tests(name='tests')",
            "foo/src/tests/index.test.mjs": textwrap.dedent(
                """\
                import assert from "assert"

                import { add } from "../index.mjs"

                it('adds 1 + 2 to equal 3', () => {
                    assert.equal(add(1, 2), 3);
                });
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo/src/tests", relative_file_path="index.test.mjs"))
    package = rule_runner.get_target(Address("foo", generated_name="pkg"))
    result = rule_runner.request(TestResult, [given_request_for(tgt, package=package)])
    if passing:
        assert b"1 passing" in result.stdout_bytes
        assert result.exit_code == 0
    else:
        assert result.exit_code == 1
        assert len(result.process_results) == ATTEMPTS_DEFAULT_OPTION


def test_jest_test_with_coverage_reporting(
    package_manager_and_version: tuple[str, str], rule_runner: RuleRunner, jest_lockfile: dict[str, str]
) -> None:
    package_manager, package_manager_version = package_manager_and_version
    rule_runner.set_options(
        args=[f"--nodejs-package-manager={package_manager}", "--test-use-coverage", "True"],
        env_inherit={"PATH"},
    )
    rule_runner.write_files(
        {
            "foo/BUILD": textwrap.dedent(
                """\
                package_json(
                    scripts=[
                        node_test_script(
                            coverage_args=['--coverage', '--coverage-directory=.coverage/'],
                            coverage_output_files=['.coverage/clover.xml'],
                        )
                    ]
                )
                """
            ),
            "foo/package.json": given_package_json(
                test_script={"test": "NODE_OPTIONS=--experimental-vm-modules jest"},
                package_manager=package_manager,
                package_manager_version=package_manager_version,
                runner={"jest": "^29.7.0"},
            ),
            **{f"foo/{key}": value for key, value in jest_lockfile.items()},
            "foo/src/BUILD": "javascript_sources()",
            "foo/src/index.mjs": make_source_to_test(),
            "foo/src/tests/BUILD": "javascript_tests(name='tests')",
            "foo/src/tests/index.test.js": textwrap.dedent(
                """\
                /**
                 * @jest-environment node
                 */

                import { expect } from "@jest/globals"

                import { add } from "../index.mjs"

                test('adds 1 + 2 to equal 3', () => {
                    expect(add(1, 2)).toBe(3);
                });
                """
            ),
        }
    )
    tgt = rule_runner.get_target(Address("foo/src/tests", relative_file_path="index.test.js"))
    package = rule_runner.get_target(Address("foo", generated_name="pkg"))
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
