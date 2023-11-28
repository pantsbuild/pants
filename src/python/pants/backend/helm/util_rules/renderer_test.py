# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest
import yaml

from pants.backend.helm.target_types import (
    HelmChartFieldSet,
    HelmChartTarget,
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
)
from pants.backend.helm.testutil import HELM_CHART_FILE, HELM_TEMPLATE_HELPERS_FILE
from pants.backend.helm.util_rules import renderer
from pants.backend.helm.util_rules.renderer import (
    HelmDeploymentCmd,
    HelmDeploymentRequest,
    RenderedHelmFiles,
    RenderHelmChartRequest,
)
from pants.backend.helm.util_rules.testutil import _read_file_from_digest
from pants.core.util_rules import external_tool, source_files
from pants.engine.addresses import Address
from pants.engine.process import InteractiveProcess
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget],
        rules=[
            *external_tool.rules(),
            *source_files.rules(),
            *renderer.rules(),
            QueryRule(InteractiveProcess, (HelmDeploymentRequest,)),
            QueryRule(RenderedHelmFiles, (HelmDeploymentRequest,)),
            QueryRule(RenderedHelmFiles, (RenderHelmChartRequest,)),
        ],
    )
    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


_COMMON_WORKSPACE_FILES = {
    "src/mychart/BUILD": "helm_chart()",
    "src/mychart/Chart.yaml": HELM_CHART_FILE,
    "src/mychart/values.yaml": dedent(
        """\
        config_maps:
            - name: foo
              data:
                foo_key: foo_value
            - name: bar
              data:
                bar_key: bar_value
        """
    ),
    "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
    "src/mychart/templates/configmap.yaml": dedent(
        """\
        {{- $root := . -}}
        {{- $allConfigMaps := .Values.config_maps -}}
        {{- range $configMap := $allConfigMaps }}
        ---
        {{- with $configMap }}
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: {{ template "fullname" $root }}-{{ .name }}
          labels:
            chart: "{{ $root.Chart.Name }}-{{ $root.Chart.Version | replace "+" "_" }}"
        data:
        {{ toYaml .data | indent 2 }}
        {{- end }}
        {{- end }}
        """
    ),
}

_DEFAULT_CONFIG_MAP = dedent(
    """\
    ---
    # Source: mychart/templates/configmap.yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: foo-mychart-foo
      labels:
        chart: "mychart-0.1.0"
    data:
      foo_key: foo_value
    ---
    # Source: mychart/templates/configmap.yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: foo-mychart-bar
      labels:
        chart: "mychart-0.1.0"
    data:
      bar_key: bar_value
    """
)


def test_sort_deployment_files_alphabetically(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_COMMON_WORKSPACE_FILES,
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
            "src/deployment/b.yaml": "",
            "src/deployment/a.yaml": "",
        }
    )

    tgt = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(tgt)

    render_request = HelmDeploymentRequest(
        cmd=HelmDeploymentCmd.UPGRADE,
        field_set=field_set,
        description="Test sort files using default sources",
    )

    render_process = rule_runner.request(InteractiveProcess, [render_request])
    assert (
        "__values/src/deployment/a.yaml,__values/src/deployment/b.yaml"
        in render_process.process.argv
    )


def test_sort_deployment_files_as_given(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_COMMON_WORKSPACE_FILES,
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart', sources=['b.yaml', '*.yaml'])",
            "src/deployment/b.yaml": "",
            "src/deployment/a.yaml": "",
        }
    )

    tgt = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(tgt)

    render_request = HelmDeploymentRequest(
        cmd=HelmDeploymentCmd.UPGRADE,
        field_set=field_set,
        description="Test sort files using default sources",
    )

    render_process = rule_runner.request(InteractiveProcess, [render_request])
    assert (
        "__values/src/deployment/b.yaml,__values/src/deployment/a.yaml"
        in render_process.process.argv
    )


def test_renders_files(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_COMMON_WORKSPACE_FILES,
            "src/deployment/BUILD": "helm_deployment(name='foo', chart='//src/mychart')",
        }
    )

    tgt = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(tgt)

    render_request = HelmDeploymentRequest(
        cmd=HelmDeploymentCmd.RENDER,
        field_set=field_set,
        description="Test template rendering",
    )

    rendered = rule_runner.request(RenderedHelmFiles, [render_request])

    assert rendered.snapshot.files
    assert not rendered.post_processed
    assert "mychart/templates/configmap.yaml" in rendered.snapshot.files

    template_output = _read_file_from_digest(
        rule_runner,
        digest=rendered.snapshot.digest,
        filename="mychart/templates/configmap.yaml",
    )
    assert template_output == _DEFAULT_CONFIG_MAP


def test_renders_files_using_deployment_values(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_COMMON_WORKSPACE_FILES,
            "src/deployment/BUILD": "helm_deployment(name='example', release_name='test', chart='//src/mychart')",
            "src/deployment/values.yaml": dedent(
                """\
                config_maps:
                  - name: example_map
                    data:
                      example_key: example_value
                """
            ),
        }
    )

    expected_rendered_config_map = dedent(
        """\
        ---
        # Source: mychart/templates/configmap.yaml
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: test-mychart-example_map
          labels:
            chart: "mychart-0.1.0"
        data:
          example_key: example_value
        """
    )

    tgt = rule_runner.get_target(Address("src/deployment", target_name="example"))
    field_set = HelmDeploymentFieldSet.create(tgt)

    render_request = HelmDeploymentRequest(
        cmd=HelmDeploymentCmd.RENDER,
        field_set=field_set,
        description="Test template rendering",
    )

    rendered = rule_runner.request(RenderedHelmFiles, [render_request])

    assert rendered.snapshot.files
    assert "mychart/templates/configmap.yaml" in rendered.snapshot.files

    template_output = _read_file_from_digest(
        rule_runner,
        digest=rendered.snapshot.digest,
        filename="mychart/templates/configmap.yaml",
    )
    assert template_output == expected_rendered_config_map


def test_ignore_missing_interpolated_keys_during_render(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_COMMON_WORKSPACE_FILES,
            "src/deployment/BUILD": dedent(
                """\
                helm_deployment(
                    name='foo',
                    chart='//src/mychart',
                    values={"foo": "{env.foo}"},
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(tgt)

    rendered = rule_runner.request(
        RenderedHelmFiles,
        [
            HelmDeploymentRequest(
                field_set,
                cmd=HelmDeploymentCmd.RENDER,
                description="Test ignore missing interpolated values",
            )
        ],
    )
    assert rendered.snapshot.files


def test_flag_dns_lookups(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/templates/configmap.yaml": dedent(
                """\
                apiVersion: v1
                kind: ConfigMap
                metadata:
                  name: foo-mychart-foo
                  labels:
                    chart: "mychart-0.1.0"
                data:
                    host_addr: "{{ getHostByName "www.google.com" }}"
                """
            ),
            "src/deployment/BUILD": dedent(
                """\
                helm_deployment(name='foo', chart='//src/mychart')
                helm_deployment(name='bar', chart='//src/mychart', enable_dns=True)
                """
            ),
        }
    )

    def render_deployment(tgt: Target):
        field_set = HelmDeploymentFieldSet.create(tgt)

        rendered = rule_runner.request(
            RenderedHelmFiles,
            [
                HelmDeploymentRequest(
                    field_set,
                    cmd=HelmDeploymentCmd.RENDER,
                    description="Test do not perform DNS lookups",
                )
            ],
        )

        template_output = _read_file_from_digest(
            rule_runner,
            digest=rendered.snapshot.digest,
            filename="mychart/templates/configmap.yaml",
        )
        return yaml.safe_load(template_output)

    foo_tgt = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    bar_tgt = rule_runner.get_target(Address("src/deployment", target_name="bar"))

    foo_rendered = render_deployment(foo_tgt)
    bar_rendered = render_deployment(bar_tgt)

    assert foo_rendered["data"]["host_addr"] == ""
    assert not bar_rendered["data"]["host_addr"] == ""


def test_render_standalone_chart(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(_COMMON_WORKSPACE_FILES)

    tgt = rule_runner.get_target(Address("src/mychart"))
    field_set = HelmChartFieldSet.create(tgt)

    rendered_files = rule_runner.request(
        RenderedHelmFiles, [RenderHelmChartRequest(field_set, release_name="foo")]
    )

    assert rendered_files.snapshot.files
    assert "mychart/templates/configmap.yaml" in rendered_files.snapshot.files
    assert not rendered_files.post_processed

    template_output = _read_file_from_digest(
        rule_runner,
        digest=rendered_files.snapshot.digest,
        filename="mychart/templates/configmap.yaml",
    )
    assert template_output == _DEFAULT_CONFIG_MAP
