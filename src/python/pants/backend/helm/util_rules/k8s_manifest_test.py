# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.helm.testutil import K8S_POD_FILE
from pants.backend.helm.util_rules import k8s_manifest
from pants.backend.helm.util_rules.k8s_manifest import (
    ContainerRef,
    ParseKubernetesManifests,
    ResourceKind,
    ResourceManifests,
)
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[],
        rules=[*k8s_manifest.rules(), QueryRule(ResourceManifests, (ParseKubernetesManifests,))],
    )


def test_parses_kube_resource_manifests(rule_runner: RuleRunner) -> None:
    manifest_digest = rule_runner.request(
        Digest, [CreateDigest([FileContent("pod.yaml", K8S_POD_FILE.encode())])]
    )
    parsed_manifests = rule_runner.request(
        ResourceManifests,
        [ParseKubernetesManifests(manifest_digest, "test_parses_kube_resource_manifests")],
    )

    assert len(parsed_manifests) == 1
    assert parsed_manifests[0].api_version == "v1"
    assert parsed_manifests[0].kind == ResourceKind.POD
    assert len(parsed_manifests[0].container_images) == 2
    assert parsed_manifests[0].container_images == (
        ContainerRef(registry=None, repository="busybox", tag="1.28"),
        ContainerRef(registry=None, repository="busybox", tag="1.29"),
    )
