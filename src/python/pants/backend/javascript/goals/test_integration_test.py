# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
import textwrap
from pathlib import Path

import pytest

from pants.backend.javascript.goals import test
from pants.backend.javascript.goals.test import JSTestFieldSet, JSTestRequest
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
    )
    return rule_runner


_SOURCE_TO_TEST = textwrap.dedent(
    """\
    export function add(x, y) {
      return x + y
    }
    """
)


def given_package_json(*, test_script: str, runner: dict[str, str]) -> str:
    return json.dumps(
        {
            "name": "pkg",
            "version": "0.0.1",
            "type": "module",
            "scripts": {"test": test_script},
            "devDependencies": runner,
            "main": "./src/index.mjs",
        }
    )


def test_jest_tests_are_successful(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "package_json()",
            "foo/package.json": given_package_json(
                test_script="NODE_OPTIONS=--experimental-vm-modules jest", runner={"jest": "^29.5"}
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
    assert result.exit_code == 0
    assert "Test Suites: 1 passed, 1 total" in result.stderr


def test_mocha_tests_are_successful(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/BUILD": "package_json()",
            "foo/package.json": given_package_json(
                test_script="mocha", runner={"mocha": "^10.2.0"}
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
    assert result.exit_code == 0
    assert "1 passing" in result.stdout
