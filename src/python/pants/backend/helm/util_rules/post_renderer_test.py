# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.target_types import (
    DockerImageTags,
    DockerImageTagsRequest,
    DockerImageTarget,
)
from pants.backend.helm.dependency_inference import deployment as infer_deployment
from pants.backend.helm.subsystems.post_renderer import (
    HELM_POST_RENDERER_CFG_FILENAME,
    HelmPostRenderer,
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
    HelmDeploymentCmd,
    HelmDeploymentRequest,
    RenderedHelmFiles,
)
from pants.backend.helm.util_rules.testutil import _read_file_from_digest
from pants.backend.helm.util_rules.tool import HelmProcess
from pants.backend.shell.target_types import ShellCommandRunTarget, ShellSourcesGeneratorTarget
from pants.backend.shell.util_rules import shell_command
from pants.core.goals import package
from pants.core.goals.run import rules as run_rules
from pants.core.util_rules import source_files
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.process import ProcessResult
from pants.engine.rules import QueryRule, rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


class CustomTestImageTagRequest(DockerImageTagsRequest):
    @classmethod
    def is_applicable(cls, target: Target) -> bool:
        return "bar" in target.address.target_name


@rule
async def custom_test_image_tags(_: CustomTestImageTagRequest) -> DockerImageTags:
    return DockerImageTags(["custom-tag"])


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[
            HelmChartTarget,
            HelmDeploymentTarget,
            DockerImageTarget,
            ShellSourcesGeneratorTarget,
            ShellCommandRunTarget,
        ],
        rules=[
            *infer_deployment.rules(),
            *source_files.rules(),
            *post_renderer.rules(),
            *run_rules(),
            *shell_command.rules(),
            *package.rules(),
            custom_test_image_tags,
            UnionRule(DockerImageTagsRequest, CustomTestImageTagRequest),
            QueryRule(HelmPostRenderer, (HelmDeploymentPostRendererRequest,)),
            QueryRule(RenderedHelmFiles, (HelmDeploymentRequest,)),
            QueryRule(ProcessResult, (HelmProcess,)),
        ],
    )
    source_root_patterns = ("src/*",)
    rule_runner.set_options(
        [f"--source-root-patterns={repr(source_root_patterns)}"],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


_TEST_GIVEN_CONFIGMAP_FILE = dedent(
    """\
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: foo-config
    data:
      foo_key: foo_value
    """
)

_TEST_EXPECTED_CONFIGMAP_FILE = (
    dedent(
        """\
      ---
      # Source: mychart/templates/configmap.yaml
      """
    )
    + _TEST_GIVEN_CONFIGMAP_FILE
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
            "src/mychart/templates/configmap.yaml": _TEST_GIVEN_CONFIGMAP_FILE,
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
            "src/deployment/BUILD": "helm_deployment(name='test', chart='//src/mychart')",
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

    expected_config_file = dedent(
        """\
        ---
        mychart/templates/pod.yaml:
        - paths:
            /spec/containers/1/image: app_foo:latest
            /spec/initContainers/0/image: init_foo:latest
        - paths:
            /spec/containers/1/image: app_bar:custom-tag
            /spec/initContainers/0/image: init_bar:custom-tag
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
              image: init_bar:custom-tag
          containers:
            - name: busy
              image: busybox:1.29
            - name: myapp-container
              image: app_bar:custom-tag
        """
    )

    deployment_addr = Address("src/deployment", target_name="test")
    tgt = rule_runner.get_target(deployment_addr)
    field_set = HelmDeploymentFieldSet.create(tgt)

    post_renderer = rule_runner.request(
        HelmPostRenderer,
        [HelmDeploymentPostRendererRequest(field_set)],
    )

    config_file = _read_file_from_digest(
        rule_runner, digest=post_renderer.digest, filename=HELM_POST_RENDERER_CFG_FILENAME
    )
    assert config_file == expected_config_file

    rendered_output = rule_runner.request(
        RenderedHelmFiles,
        [
            HelmDeploymentRequest(
                field_set=field_set,
                cmd=HelmDeploymentCmd.RENDER,
                description="Test post-renderer output",
                post_renderer=post_renderer,
            )
        ],
    )
    assert "mychart/templates/pod.yaml" in rendered_output.snapshot.files
    assert "mychart/templates/configmap.yaml" in rendered_output.snapshot.files

    rendered_configmap_file = _read_file_from_digest(
        rule_runner,
        digest=rendered_output.snapshot.digest,
        filename="mychart/templates/configmap.yaml",
    )
    assert rendered_configmap_file == _TEST_EXPECTED_CONFIGMAP_FILE

    rendered_pod_file = _read_file_from_digest(
        rule_runner, digest=rendered_output.snapshot.digest, filename="mychart/templates/pod.yaml"
    )
    assert rendered_pod_file == expected_rendered_pod


def test_use_simple_extra_post_renderer(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/mychart/BUILD": "helm_chart()",
            "src/mychart/Chart.yaml": HELM_CHART_FILE,
            "src/mychart/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/mychart/templates/configmap.yaml": _TEST_GIVEN_CONFIGMAP_FILE,
            "src/shell/BUILD": dedent(
                """\
              shell_sources(name="scripts")

              run_shell_command(
                name="custom_post_renderer",
                command="src/shell/my-script.sh",
                execution_dependencies=[":scripts"]
              )
              """
            ),
            "src/deployment/BUILD": dedent(
                """\
              helm_deployment(
                name="test",
                chart="//src/mychart",
                post_renderers=["//src/shell:custom_post_renderer"]
              )
              """
            ),
        }
    )

    # We need to create the post-renderer script as a digest to ensure it has running permissions.
    post_renderer_script_digest = rule_runner.request(
        Digest,
        [
            CreateDigest(
                [
                    FileContent(
                        path="src/shell/my-script.sh",
                        content=dedent(
                            """\
                            #!/bin/bash
                            cat <&0
                            """
                        ).encode(),
                        is_executable=True,
                    )
                ]
            )
        ],
    )

    rule_runner.write_digest(post_renderer_script_digest)

    deployment_addr = Address("src/deployment", target_name="test")
    tgt = rule_runner.get_target(deployment_addr)
    field_set = HelmDeploymentFieldSet.create(tgt)

    post_renderer = rule_runner.request(
        HelmPostRenderer,
        [HelmDeploymentPostRendererRequest(field_set)],
    )

    rendered_output = rule_runner.request(
        RenderedHelmFiles,
        [
            HelmDeploymentRequest(
                field_set=field_set,
                cmd=HelmDeploymentCmd.RENDER,
                description="Test post-renderer output",
                post_renderer=post_renderer,
            )
        ],
    )
    assert "mychart/templates/configmap.yaml" in rendered_output.snapshot.files

    rendered_configmap_file = _read_file_from_digest(
        rule_runner,
        digest=rendered_output.snapshot.digest,
        filename="mychart/templates/configmap.yaml",
    )
    assert rendered_configmap_file == _TEST_EXPECTED_CONFIGMAP_FILE
