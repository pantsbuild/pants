# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Any

import pytest
import yaml

from pants.backend.helm.testutil import HELM_CHART_FILE_V1_FULL, HELM_CHART_FILE_V2_FULL
from pants.backend.helm.util_rules import chart_metadata
from pants.backend.helm.util_rules.chart_metadata import (
    HelmChartMetadata,
    ParseHelmChartMetadataDigest,
)
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[],
        rules=[
            *chart_metadata.rules(),
            QueryRule(Digest, (HelmChartMetadata,)),
            QueryRule(HelmChartMetadata, (ParseHelmChartMetadataDigest,)),
        ],
    )


_TEST_METADATA_PARSER_PARAMS = [
    (HELM_CHART_FILE_V1_FULL),
    (HELM_CHART_FILE_V2_FULL),
]


def assert_metadata(metadata: HelmChartMetadata, expected: dict[str, Any]) -> None:
    # Amend the expected chart dictionary so the two dicts can be safely compared.
    if metadata.api_version == "v1":
        expected["apiVersion"] = "v1"

    assert expected == metadata.to_json_dict()


@pytest.mark.parametrize("chart_contents", _TEST_METADATA_PARSER_PARAMS)
def test_metadata_parser_syntax(chart_contents: str) -> None:
    chart_dict = yaml.safe_load(chart_contents)
    metadata = HelmChartMetadata.from_bytes(chart_contents.encode("utf-8"))

    assert_metadata(metadata, chart_dict)


@pytest.mark.parametrize("chart_contents", _TEST_METADATA_PARSER_PARAMS)
def test_parse_metadata_digest(rule_runner: RuleRunner, chart_contents: str) -> None:
    chart_dict = yaml.safe_load(chart_contents)
    chart_bytes = bytes(chart_contents, "utf-8")

    non_prefixed_digest = rule_runner.request(
        Digest, [CreateDigest([FileContent("Chart.yaml", chart_bytes)])]
    )
    non_prefixed_metadata = rule_runner.request(
        HelmChartMetadata,
        [
            ParseHelmChartMetadataDigest(
                non_prefixed_digest, description_of_origin="test_parse_metadata_digest"
            )
        ],
    )

    assert_metadata(non_prefixed_metadata, chart_dict)


def test_raises_error_if_more_than_one_metadata_file(rule_runner: RuleRunner) -> None:
    digest = rule_runner.request(
        Digest,
        [
            CreateDigest(
                [
                    FileContent("Chart.yaml", HELM_CHART_FILE_V1_FULL.encode()),
                    FileContent("Chart.yml", HELM_CHART_FILE_V2_FULL.encode()),
                ]
            )
        ],
    )

    with pytest.raises(ExecutionError, match="Found more than one Helm chart metadata file at"):
        rule_runner.request(
            HelmChartMetadata,
            [
                ParseHelmChartMetadataDigest(
                    digest,
                    description_of_origin="test_raises_error_if_more_than_one_metadata_file",
                )
            ],
        )


@pytest.mark.parametrize("chart_contents", _TEST_METADATA_PARSER_PARAMS)
def test_render_metadata_digest(rule_runner: RuleRunner, chart_contents: str) -> None:
    metadata = HelmChartMetadata.from_bytes(chart_contents.encode("utf-8"))

    rendered_digest = rule_runner.request(Digest, [metadata])
    parsed_metadata = rule_runner.request(
        HelmChartMetadata,
        [
            ParseHelmChartMetadataDigest(
                rendered_digest, description_of_origin="test_render_metadata_digest"
            )
        ],
    )

    assert parsed_metadata == metadata
