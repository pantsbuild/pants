# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import PurePath
from textwrap import dedent

import pytest

from pants.backend.helm.util_rules import manifest
from pants.backend.helm.util_rules.manifest import (
    ImageRef,
    KubeManifests,
    ParseKubeManifests,
    StandardKind,
)
from pants.backend.helm.util_rules.yaml_utils import YamlPath
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[],
        rules=[*manifest.rules(), QueryRule(KubeManifests, (ParseKubeManifests,))],
    )


K8S_POD_FILE = dedent(
    """\
    apiVersion: v1
    kind: Pod
    metadata:
      name: foo
      labels:
        chart: foo-bar
    spec:
      containers:
        - name: myapp-container
          image: busybox:1.28
      initContainers:
        - name: init-service
          image: busybox:1.29
    """
)

K8S_CRONJOB_FILE = dedent(
    """\
    apiVersion: batch/v1
    kind: CronJob
    metadata:
      name: hello
    spec:
      schedule: "* * * * *"
      jobTemplate:
        spec:
          template:
            spec:
              containers:
              - name: hello
                image: busybox:1.28
                imagePullPolicy: IfNotPresent
                command:
                - /bin/sh
                - -c
                - date; echo Hello from the Kubernetes cluster
              initContainers:
              - name: init-service
                image: busybox:1.29
              restartPolicy: OnFailure
    """
)

_TEST_KUBE_FILES_TO_PARSE_PARAMS = [
    (K8S_POD_FILE, "v1", StandardKind.POD),
    (K8S_CRONJOB_FILE, "batch/v1", StandardKind.CRON_JOB),
]


@pytest.mark.parametrize("manifest, api_version, kind", _TEST_KUBE_FILES_TO_PARSE_PARAMS)
def test_parses_kube_resource_manifests(
    rule_runner: RuleRunner, manifest: str, api_version: str, kind: StandardKind
) -> None:
    manifest_digest = rule_runner.request(
        Digest, [CreateDigest([FileContent("manifest.yaml", manifest.encode())])]
    )
    parsed_manifests = rule_runner.request(
        KubeManifests,
        [ParseKubeManifests(manifest_digest, "test_parses_kube_resource_manifests")],
    )

    if kind == StandardKind.POD:
        expected_spec_path = YamlPath.parse("/spec")
    else:
        expected_spec_path = YamlPath.parse("/spec/jobTemplate/spec/template/spec")

    assert len(parsed_manifests) == 1
    assert parsed_manifests[0].api_version == api_version
    assert parsed_manifests[0].kind == kind
    assert parsed_manifests[0].filename == PurePath("manifest.yaml")

    assert len(parsed_manifests[0].all_containers) == 2
    assert parsed_manifests[0].pod_spec
    assert parsed_manifests[0].pod_spec.element_path == expected_spec_path

    assert len(parsed_manifests[0].pod_spec.containers) == 1
    assert len(parsed_manifests[0].pod_spec.init_containers) == 1
    assert (
        parsed_manifests[0].pod_spec.containers[0].element_path
        == expected_spec_path / "containers" / "0"
    )
    assert (
        parsed_manifests[0].pod_spec.init_containers[0].element_path
        == expected_spec_path / "initContainers" / "0"
    )

    parsed_image_refs = [container.image for container in parsed_manifests[0].all_containers]
    assert parsed_image_refs == [
        ImageRef(registry=None, repository="busybox", tag="1.28"),
        ImageRef(registry=None, repository="busybox", tag="1.29"),
    ]


def test_parse_multiple_manifests_in_single_file(rule_runner: RuleRunner) -> None:
    manifest_contents = K8S_POD_FILE + "---\n" + K8S_CRONJOB_FILE
    manifest_digest = rule_runner.request(
        Digest, [CreateDigest([FileContent("manifest.yml", manifest_contents.encode())])]
    )

    parsed_manifests = rule_runner.request(
        KubeManifests,
        [ParseKubeManifests(manifest_digest, "test_parse_multiple_manifests_in_single_file")],
    )

    assert len(parsed_manifests) == 2


def test_no_manifests_parsed(rule_runner: RuleRunner) -> None:
    digest = rule_runner.request(Digest, [CreateDigest([FileContent("file.txt", "foo".encode())])])

    parsed_manifests = rule_runner.request(
        KubeManifests,
        [ParseKubeManifests(digest, "test_no_manifests_parsed")],
    )

    assert len(parsed_manifests) == 0
