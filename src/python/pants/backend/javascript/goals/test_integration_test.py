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
from pants.backend.javascript.goals.test import JSCoverageData, JSTestFieldSet, JSTestRequest
from pants.backend.javascript.package_json import PackageJsonTarget
from pants.backend.javascript.target_types import (
    JSSourcesGeneratorTarget,
    JSTestsGeneratorTarget,
    JSTestTarget,
)
from pants.build_graph.address import Address
from pants.core.goals.test import TestResult, get_filtered_environment
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
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
    return rule_runner


_SOURCE_TO_TEST = textwrap.dedent(
    """\
    export function add(x, y) {
      return x + y
    }
    """
)


def given_package_json(*, test_script: dict[str, str], runner: dict[str, str]) -> str:
    return json.dumps(
        {
            "name": "pkg",
            "version": "0.0.1",
            "type": "module",
            "scripts": {**test_script},
            "devDependencies": runner,
            "main": "./src/index.mjs",
        }
    )


@pytest.mark.parametrize(
    "test_script,package_json_target",
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
def test_jest_tests_are_successful(
    rule_runner: RuleRunner, test_script: dict[str, str], package_json_target: str
) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": package_json_target,
            "foo/package.json": given_package_json(
                test_script=test_script, runner={"jest": "^29.5"}
            ),
            "foo/package-lock.json": (
                Path(__file__).parent / "jest_resources/package-lock.json"
            ).read_text(),
            "foo/src/BUILD": "javascript_sources()",
            "foo/src/index.mjs": _SOURCE_TO_TEST,
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
    result = rule_runner.request(
        TestResult, [JSTestRequest.Batch("", (JSTestFieldSet.create(tgt),), None)]
    )
    assert "Test Suites: 1 passed, 1 total" in result.stderr
    assert result.exit_code == 0


def test_mocha_tests_are_successful(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "package_json()",
            "foo/package.json": given_package_json(
                test_script={"test": "mocha"}, runner={"mocha": "^10.2.0"}
            ),
            "foo/package-lock.json": (
                Path(__file__).parent / "mocha_resources/package-lock.json"
            ).read_text(),
            "foo/src/BUILD": "javascript_sources()",
            "foo/src/index.mjs": _SOURCE_TO_TEST,
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
    result = rule_runner.request(
        TestResult, [JSTestRequest.Batch("", (JSTestFieldSet.create(tgt),), None)]
    )
    assert "1 passing" in result.stdout
    assert result.exit_code == 0


def test_jest_test_with_coverage_reporting(rule_runner: RuleRunner) -> None:
    rule_runner.set_options(args=["--test-use-coverage", "True"])
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
                runner={"jest": "^29.5"},
            ),
            "foo/package-lock.json": (
                Path(__file__).parent / "jest_resources/package-lock.json"
            ).read_text(),
            "foo/src/BUILD": "javascript_sources()",
            "foo/src/index.mjs": _SOURCE_TO_TEST,
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
    result = rule_runner.request(
        TestResult, [JSTestRequest.Batch("", (JSTestFieldSet.create(tgt),), None)]
    )
    assert result.coverage_data

    rule_runner.write_digest(cast(JSCoverageData, result.coverage_data).snapshot.digest)
    assert Path(rule_runner.build_root, ".coverage/clover.xml").exists()
