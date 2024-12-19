# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json

from pants.core.goals.lint import LintResult

trivy_config = """
format: json
"""


def assert_trivy_output(
    result: LintResult,
    expected_exit_code: int,
    target: str,
    scanner_type: str,
    expected_error_count: int,
):
    if result.exit_code != expected_exit_code:
        raise AssertionError(
            f"Trivy process had incorrect exit code, expected={expected_exit_code}, actual={result.exit_code}, stdout={result.stdout}, stderr={result.stderr}"
        )

    try:
        report = json.loads(result.stdout)
    except json.decoder.JSONDecodeError as e:
        raise AssertionError(
            f"Trivy output could not be parsed as JSON, stdout={result.stdout=}, stderr={result.stderr}"
        ) from e

    findings_by_target = {res["Target"]: res for res in report["Results"]}
    assert (
        target in findings_by_target
    ), f"Did not find expected file in results, target={target} files={list(findings_by_target.keys())}"

    if scanner_type == "config":
        found_count = findings_by_target[target]["MisconfSummary"]["Failures"]
        assert (
            found_count == expected_error_count
        ), f"Did not find expected failure count actual={found_count} expected={expected_error_count}"
    elif scanner_type == "image":
        found_count = len(findings_by_target[target]["Vulnerabilities"])
        assert (
            found_count == expected_error_count
        ), f"Did not find expected vulnerabilities found={found_count} expected={expected_error_count}"


def assert_trivy_success(result: LintResult):
    if result.exit_code != 0:
        raise AssertionError(f"Trivy process was not successful, stdout={result.stdout}")

    try:
        json.loads(result.stdout)
    except json.decoder.JSONDecodeError as e:
        raise AssertionError(
            f"Trivy output could not be parsed as JSON, stdout={result.stdout}, stderr={result.stderr}"
        ) from e
