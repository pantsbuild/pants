# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.target_types import (
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
)
from pants.core.util_rules import external_tool, source_files
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents, DigestSubset, PathGlobs
from pants.engine.internals.native_engine import Digest
from pants.engine.process import InteractiveProcess
from pants.engine.rules import QueryRule
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
        ],
    )
    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


def _read_file_from_digest(rule_runner: RuleRunner, *, digest: Digest, filename: str) -> str:
    config_file_digest = rule_runner.request(Digest, [DigestSubset(digest, PathGlobs([filename]))])
    config_file_contents = rule_runner.request(DigestContents, [config_file_digest])
    return config_file_contents[0].content.decode("utf-8")


def _common_workspace_files() -> dict[str, str]:
    return {
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


def test_sort_deployment_files_alphabetically(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_common_workspace_files(),
            "src/deployment/BUILD": "helm_deployment(name='foo', dependencies=['//src/mychart'])",
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
            **_common_workspace_files(),
            "src/deployment/BUILD": "helm_deployment(name='foo', dependencies=['//src/mychart'], sources=['b.yaml', '*.yaml'])",
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
            **_common_workspace_files(),
            "src/deployment/BUILD": "helm_deployment(name='foo', dependencies=['//src/mychart'])",
        }
    )

    tgt = rule_runner.get_target(Address("src/deployment", target_name="foo"))
    field_set = HelmDeploymentFieldSet.create(tgt)

    expected_config_map_file = dedent(
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
    assert template_output == expected_config_map_file


def test_ignore_missing_interpolated_keys_during_render(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            **_common_workspace_files(),
            "src/deployment/BUILD": dedent(
                """\
                helm_deployment(
                    name='foo',
                    dependencies=['//src/mychart'],
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
