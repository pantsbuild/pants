# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import random
from textwrap import dedent

import pytest
import yaml

from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.testutil import (
    HELM_BATCH_HOOK_TEMPLATE,
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_CRD_FILE,
    K8S_SERVICE_TEMPLATE,
)
from pants.backend.helm.util_rules import chart, render, tool
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.render import RenderedHelmChart, RenderHelmChartRequest
from pants.core.util_rules import external_tool, stripped_source_files
from pants.engine.addresses import Address
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    PathGlobs,
    Snapshot,
)
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget],
        rules=[
            *external_tool.rules(),
            *chart.rules(),
            *render.rules(),
            *stripped_source_files.rules(),
            *tool.rules(),
            QueryRule(HelmChart, (HelmChartRequest,)),
            QueryRule(RenderedHelmChart, (RenderHelmChartRequest,)),
            QueryRule(Snapshot, (CreateDigest,)),
        ],
    )


def _read_rendered_resource(
    rule_runner: RuleRunner, render_request: RenderHelmChartRequest, path: str
):
    rendered = rule_runner.request(RenderedHelmChart, [render_request])

    assert rendered.snapshot
    assert path in rendered.snapshot.files

    rendered_template_digest = rule_runner.request(
        Digest, [DigestSubset(rendered.snapshot.digest, PathGlobs([path]))]
    )
    rendered_template_contents = rule_runner.request(DigestContents, [rendered_template_digest])

    assert len(rendered_template_contents) == 1
    return yaml.safe_load(rendered_template_contents[0].content.decode())


def test_template_rendering_values(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='foo')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    default_values_file = dedent(
        """\
        service:
          externalPort: 1111
        """
    )
    override_values_file = dedent(
        """\
        service:
          externalPort: 1234
        """
    )
    additional_values_file = dedent(
        """\
        service:
          internalPort: 4321
        """
    )
    value_files_snapshot = rule_runner.request(
        Snapshot,
        [
            CreateDigest(
                [
                    FileContent("values.yaml", default_values_file.encode()),
                    FileContent("additional_values.yaml", additional_values_file.encode()),
                    FileContent("values_override.yaml", override_values_file.encode()),
                ]
            )
        ],
    )

    values = {"service.name": "bar"}

    target = rule_runner.get_target(Address("", target_name="foo"))
    chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])

    parsed_service = _read_rendered_resource(
        rule_runner,
        RenderHelmChartRequest(chart, values_snapshot=value_files_snapshot, values=values),
        "templates/service.yaml",
    )
    assert parsed_service["spec"]["ports"][0]["name"] == "bar"
    assert parsed_service["spec"]["ports"][0]["port"] == 1234
    assert parsed_service["spec"]["ports"][0]["targetPort"] == 4321


def test_render_skip_crds(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='foo')",
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "crds/foo.yaml": K8S_CRD_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_TEMPLATE,
        }
    )

    target = rule_runner.get_target(Address("", target_name="foo"))
    chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])

    rendered = rule_runner.request(
        RenderedHelmChart, [RenderHelmChartRequest(chart, skip_crds=True)]
    )
    assert "crds/foo.yaml" not in rendered.snapshot.files


def test_template_render_kube_version(rule_runner: RuleRunner) -> None:
    config_map_template = dedent(
        """\
        apiVersion: v1
        kind: ConfigMap
        metadata:
        name: kube_configmap
        data:
          kube_version: {{ .Capabilities.KubeVersion }}
          kube_version_major: {{ .Capabilities.KubeVersion.Major }}
          kube_version_minor: {{ .Capabilities.KubeVersion.Minor }}
        """
    )
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='foo')",
            "Chart.yaml": HELM_CHART_FILE,
            "templates/configmap.yaml": config_map_template,
        }
    )

    target = rule_runner.get_target(Address("", target_name="foo"))
    chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])

    kube_version_major = random.randint(1, 1000)
    kube_version_minor = random.randint(1, 1000)
    render_request = RenderHelmChartRequest(
        chart, kube_version=f"{kube_version_major}.{kube_version_minor}"
    )

    parsed_configmap = _read_rendered_resource(
        rule_runner, render_request, "templates/configmap.yaml"
    )
    assert (
        parsed_configmap["data"]["kube_version"] == f"v{kube_version_major}.{kube_version_minor}.0"
    )
    assert parsed_configmap["data"]["kube_version_major"] == kube_version_major
    assert parsed_configmap["data"]["kube_version_minor"] == kube_version_minor


def test_template_render_api_versions(rule_runner: RuleRunner) -> None:
    config_map_template = dedent(
        """\
        apiVersion: v1
        kind: ConfigMap
        metadata:
        name: apiversions_configmap
        data:
          api_versions: {{ .Capabilities.APIVersions | toJson }}
        """
    )
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='foo')",
            "Chart.yaml": HELM_CHART_FILE,
            "templates/configmap.yaml": config_map_template,
        }
    )

    target = rule_runner.get_target(Address("", target_name="foo"))
    chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])

    render_request = RenderHelmChartRequest(chart, api_versions=["foo/v1beta1", "bar/v1"])

    parsed_configmap = _read_rendered_resource(
        rule_runner, render_request, "templates/configmap.yaml"
    )
    api_versions = parsed_configmap["data"]["api_versions"]
    assert "foo/v1beta1" in api_versions
    assert "bar/v1" in api_versions


def test_template_render_hooks(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "helm_chart(name='foo')",
            "Chart.yaml": HELM_CHART_FILE,
            "templates/post-install-job.yaml": HELM_BATCH_HOOK_TEMPLATE,
        }
    )

    target = rule_runner.get_target(Address("", target_name="foo"))
    chart = rule_runner.request(HelmChart, [HelmChartRequest.from_target(target)])

    rendered_chart = rule_runner.request(RenderedHelmChart, [RenderHelmChartRequest(chart)])
    assert "templates/post-install-job.yaml" in rendered_chart.snapshot.files

    nohook_rendered_chart = rule_runner.request(
        RenderedHelmChart, [RenderHelmChartRequest(chart, no_hooks=True)]
    )
    assert "templates/post-install-job.yaml" not in nohook_rendered_chart.snapshot.files
