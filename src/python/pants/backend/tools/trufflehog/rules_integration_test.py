# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from typing import Any

import pytest

from pants.backend.tools.trufflehog.rules import TrufflehogRequest
from pants.backend.tools.trufflehog.rules import rules as trufflehog_rules
from pants.core.goals.fmt import Partitions
from pants.core.goals.lint import LintResult
from pants.core.util_rules import config_files, external_tool
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *trufflehog_rules(),
            *config_files.rules(),
            *external_tool.rules(),
            QueryRule(Partitions, [TrufflehogRequest.PartitionRequest]),
            QueryRule(LintResult, [TrufflehogRequest.Batch]),
        ],
    )


PANTS_TOML = """[GLOBAL]\nbackend_packages = ["pants.backend.tools.trufflehog"]\n"""

# This configuration file specifies a detector that looks for custom regex patterns
TRUFFLEHOG_CONFIG = r"""
# config.yaml
detectors:
  - name: HogTokenDetector
    keywords:
      - hog
    regex:
      hogID: '\b(HOG[0-9A-Z]{17})\b'
      hogToken: '[^A-Za-z0-9+\/]{0,1}([A-Za-z0-9+\/]{40})[^A-Za-z0-9+\/]{0,1}'
    verify:
      - endpoint: http://localhost:8000/
        # unsafe must be set if the endpoint is HTTP
        unsafe: true
        headers:
          - "Authorization: super secret authorization header"
"""

# Example file contents with mock secrets in place for detection. These are not real secrets.
TRUFFLEHOG_PAYLOAD_WITH_SECRETS = """
{
    "HogTokenDetector": {
        "HogID": ["HOGAAIUNNWHAHJJWUQYR"],
        "HogSecret": ["sD9vzqdSsAOxntjAJ/qZ9sw+8PvEYg0r7D1Hhh0C"],
    }
}
"""

# The count of detectors loaded by the current version of Trufflehog.
# This may change in future versions, depending on whether or not new detectors are added.
TOTAL_DETECTORS = 738


def run_trufflehog(
    rule_runner: RuleRunner,
    *,
    extra_args: list[str] | None = None,
) -> LintResult:
    rule_runner.set_options(
        ["--backend-packages=pants.backend.tools.trufflehog", *(extra_args or ())],
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**"])])
    partition = rule_runner.request(
        Partitions[Any], [TrufflehogRequest.PartitionRequest(snapshot.files)]
    )[0]
    fmt_result = rule_runner.request(
        LintResult,
        [
            TrufflehogRequest.Batch("", partition.elements, partition_metadata=partition.metadata),
        ],
    )
    return fmt_result


def extract_total_detector_count(input_string: str) -> int | None:
    """This function extracts the total number of detectors loaded by Trufflehog.

    Trufflehog prints to stderr in a format that can't be parsed as json.
    """
    # Find the index of the substring "total"
    total_index = input_string.find('"total":')
    if total_index == -1:
        return None  # "total" key not found

    # Extract the value after "total"
    total_value = ""
    for char in input_string[total_index + len('"total":') :]:
        if char.isdigit():
            total_value += char
        else:
            break

    return int(total_value) if total_value else None


def test_detectors_loaded(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"pants-enable-trufflehog.toml": PANTS_TOML})
    fmt_result = run_trufflehog(rule_runner)
    assert not fmt_result.stdout
    # Trufflehog prints details on how many active detectors are running to stderr
    assert "loaded detectors" in fmt_result.stderr
    # This number is expected to change with upgrades to trufflehog
    assert TOTAL_DETECTORS == extract_total_detector_count(fmt_result.stderr)
    rule_runner.write_files(
        {
            "pants-enable-trufflehog.toml.toml": PANTS_TOML,
            "trufflehog-config.yaml": TRUFFLEHOG_CONFIG,
        }
    )
    fmt_result = run_trufflehog(rule_runner)
    assert not fmt_result.stdout
    # Adding the config file has added one additional detector
    assert TOTAL_DETECTORS + 1 == extract_total_detector_count(fmt_result.stderr)


def test_secret_detected(rule_runner: RuleRunner) -> None:
    # Write the configuration file
    rule_runner.write_files(
        {
            "pants-enable-trufflehog.toml.toml": PANTS_TOML,
            "trufflehog-config.yaml": TRUFFLEHOG_CONFIG,
            "secret.json": TRUFFLEHOG_PAYLOAD_WITH_SECRETS,
        }
    )
    fmt_result = run_trufflehog(rule_runner)

    # Trufflehog returns exit code 183 upon finding secrets
    assert fmt_result.exit_code == 183
