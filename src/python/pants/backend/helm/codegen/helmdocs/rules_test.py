# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.codegen.helmdocs.rules import GenerateHelmDocsRequest
from pants.backend.helm.codegen.helmdocs.rules import rules as helmdocs_rules
from pants.backend.helm.target_types import HelmChartMetaSourceField, HelmChartTarget
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
)
from pants.backend.helm.util_rules import sources
from pants.backend.helm.util_rules.sources import HelmChartSourceFiles, HelmChartSourceFilesRequest
from pants.build_graph.address import Address
from pants.core.target_types import FilesGeneratorTarget, FileTarget, generate_targets_from_files
from pants.core.util_rules import config_files, external_tool, stripped_source_files
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources, HydratedSources, HydrateSourcesRequest
from pants.source import source_root
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, FileTarget, FilesGeneratorTarget],
        rules=[
            *sources.rules(),
            *config_files.rules(),
            *external_tool.rules(),
            *stripped_source_files.rules(),
            *source_root.rules(),
            *helmdocs_rules(),
            generate_targets_from_files,
            QueryRule(HelmChartSourceFiles, (HelmChartSourceFilesRequest,)),
            QueryRule(HydratedSources, [HydrateSourcesRequest]),
            QueryRule(GeneratedSources, [GenerateHelmDocsRequest]),
        ],
    )


def test_generates_readme_docs(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='mychart')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="mychart"))
    chart_sources = rule_runner.request(
        HydratedSources, [HydrateSourcesRequest(tgt[HelmChartMetaSourceField])]
    )
    generated_sources = rule_runner.request(
        GeneratedSources, [GenerateHelmDocsRequest(chart_sources.snapshot, tgt)]
    )

    assert len(generated_sources.snapshot.files) == 1
    assert "README.md" in generated_sources.snapshot.files


def test_packaged_chart_contains_generated_readme(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                helm_chart(name='mychart')
                """
            ),
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
        }
    )

    tgt = rule_runner.get_target(Address("", target_name="mychart"))
    source_files = rule_runner.request(
        HelmChartSourceFiles,
        [HelmChartSourceFilesRequest.create(tgt, include_metadata=True, generate_docs=True)],
    )

    assert len(source_files.snapshot.files) == 5
    assert "README.md" in source_files.snapshot.files
