# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json

trivy_config = """
format: json
"""


def assert_trivy_output(
    result, expected_exit_code: int, target: str, error_type: str, expected_error_count: int
):
    assert result.exit_code == expected_exit_code
    report = json.loads(result.stdout)
    findings_by_target = {res["Target"]: res for res in report["Results"]}
    assert (
        target in findings_by_target
    ), f"Did not find expected file in results, target={target} files={list(findings_by_target.keys())}"
    if error_type == "terraform":
        assert (
            findings_by_target[target]["MisconfSummary"]["Failures"] == expected_error_count
        ), "Did not find expected failure count"
    elif error_type == "docker":
        found_count = len(findings_by_target[target]["Vulnerabilities"])
        assert (
            found_count == expected_error_count
        ), f"Did not find expected vulnerabilities found={found_count} expected={expected_error_count}"
