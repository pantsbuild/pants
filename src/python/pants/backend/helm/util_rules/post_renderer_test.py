# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.target_types import DockerImageTarget
from pants.backend.helm.dependency_inference import deployment as infer_deployment
from pants.backend.helm.subsystems.post_renderer import (
    HELM_POST_RENDERER_CFG_FILENAME,
    HelmPostRendererRunnable,
)
from pants.backend.helm.target_types import (
    HelmChartTarget,
    HelmDeploymentFieldSet,
    HelmDeploymentTarget,
)
from pants.backend.helm.testutil import HELM_CHART_FILE, HELM_TEMPLATE_HELPERS_FILE
from pants.backend.helm.util_rules import post_renderer
from pants.backend.helm.util_rules.post_renderer import HelmDeploymentPostRendererRequest
from pants.backend.helm.util_rules.renderer import (
    HelmDeploymentRendererCmd,
    HelmDeploymentRendererRequest,
    RenderedFiles,
)
from pants.backend.helm.util_rules.renderer_test import _read_file_from_digest
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.engine.addresses import Address
from pants.engine.process import ProcessResult
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, HelmDeploymentTarget, DockerImageTarget],
        rules=[
            *infer_deployment.rules(),
            *post_renderer.rules(),
            QueryRule(HelmPostRendererRunnable, (HelmDeploymentPostRendererRequest,)),
            QueryRule(RenderedFiles, (HelmDeploymentRendererRequest,)),
            QueryRule(ProcessResult, (HelmProcess,)),
        ],
    )


def test_can_prepare_post_renderer(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/values.yaml": dedent(
                """\
                pods: []
                """
            ),
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/pod.yaml": dedent(
                """\
                {{- $root := . -}}
                {{- range $pod := .Values.pods }}
                ---
                apiVersion: v1
                kind: Pod
                metadata:
                  name: {{ template "fullname" $root }}-{{ $pod.name }}
                  labels:
                    chart: "{{ $root.Chart.Name }}-{{ $root.Chart.Version | replace "+" "_" }}"
                spec:
                  initContainers:
                    - name: myapp-init-container
                      image: {{ $pod.initContainerImage }}
                  containers:
                    - name: busy
                      image: busybox:1.29
                    - name: myapp-container
                      image: {{ $pod.appImage }}
                {{- end }}
                """
            ),
            "src/deployment/BUILD": "helm_deployment(name='test', dependencies=['//src/mychart'])",
            "src/deployment/values.yaml": dedent(
                """\
                pods:
                  - name: foo
                    initContainerImage: src/image:init_foo
                    appImage: src/image:app_foo
                  - name: bar
                    initContainerImage: src/image:init_bar
                    appImage: src/image:app_bar
                """
            ),
            "src/image/BUILD": dedent(
                """\
                docker_image(name="init_foo", source="Dockerfile.init")
                docker_image(name="app_foo", source="Dockerfile.app")

                docker_image(name="init_bar", source="Dockerfile.init")
                docker_image(name="app_bar", source="Dockerfile.app")
                """
            ),
            "src/image/Dockerfile.init": "FROM busybox:1.28",
            "src/image/Dockerfile.app": "FROM busybox:1.28",
        }
    )

    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    expected_config_file = dedent(
        """\
        ---
        mychart/templates/pod.yaml:
        - paths:
            /spec/containers/1/image: app_foo:latest
            /spec/initContainers/0/image: init_foo:latest
        - paths:
            /spec/containers/1/image: app_bar:latest
            /spec/initContainers/0/image: init_bar:latest
        """
    )

    expected_rendered_pod = dedent(
        """\
        ---
        # Source: mychart/templates/pod.yaml
        apiVersion: v1
        kind: Pod
        metadata:
          name: test-mychart-foo
          labels:
            chart: mychart-0.1.0
        spec:
          initContainers:
            - name: myapp-init-container
              image: init_foo:latest
          containers:
            - name: busy
              image: busybox:1.29
            - name: myapp-container
              image: app_foo:latest
        ---
        # Source: mychart/templates/pod.yaml
        apiVersion: v1
        kind: Pod
        metadata:
          name: test-mychart-bar
          labels:
            chart: mychart-0.1.0
        spec:
          initContainers:
            - name: myapp-init-container
              image: init_bar:latest
          containers:
            - name: busy
              image: busybox:1.29
            - name: myapp-container
              image: app_bar:latest
        """
    )

    deployment_addr = Address("src/deployment", target_name="test")
    tgt = rule_runner.get_target(deployment_addr)
    field_set = HelmDeploymentFieldSet.create(tgt)

    post_renderer = rule_runner.request(
        HelmPostRendererRunnable,
        [HelmDeploymentPostRendererRequest(field_set)],
    )

    config_file = _read_file_from_digest(
        rule_runner, digest=post_renderer.digest, filename=HELM_POST_RENDERER_CFG_FILENAME
    )
    assert config_file == expected_config_file

    rendered_output = rule_runner.request(
        RenderedFiles,
        [
            HelmDeploymentRendererRequest(
                field_set=field_set,
                cmd=HelmDeploymentRendererCmd.TEMPLATE,
                description="Test post-renderer output",
                post_renderer=post_renderer,
            )
        ],
    )
    assert "mychart/templates/pod.yaml" in rendered_output.snapshot.files

    rendered_pod_file = _read_file_from_digest(
        rule_runner, digest=rendered_output.snapshot.digest, filename="mychart/templates/pod.yaml"
    )
    assert rendered_pod_file == expected_rendered_pod
