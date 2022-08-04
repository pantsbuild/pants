# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.helm.subsystems import k8s_parser
from pants.backend.helm.subsystems.k8s_parser import ParsedKubeManifest, ParseKubeManifestRequest
from pants.backend.helm.testutil import K8S_POD_FILE
from pants.backend.helm.utils.yaml import YamlPath
from pants.engine.fs import CreateDigest, Digest, FileContent
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *k8s_parser.rules(),
            QueryRule(ParsedKubeManifest, (ParseKubeManifestRequest,)),
        ]
    )
    rule_runner.set_options(
        [],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    return rule_runner


def test_parser_can_run(rule_runner: RuleRunner) -> None:
    file_digest = rule_runner.request(
        Digest, [CreateDigest([FileContent("pod.yaml", K8S_POD_FILE.encode("utf-8"))])]
    )

    parsed_manifest = rule_runner.request(
        ParsedKubeManifest, [ParseKubeManifestRequest("pod.yaml", file_digest)]
    )

    expected_image_refs = [
        (0, YamlPath.parse("/spec/containers/0/image"), "busybox:1.28"),
        (0, YamlPath.parse("/spec/initContainers/0/image"), "busybox:1.29"),
    ]

    assert parsed_manifest.found_image_refs == tuple(expected_image_refs)
