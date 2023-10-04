# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import cast

import pytest

from pants.backend.helm.subsystems import k8s_parser
from pants.backend.helm.subsystems.k8s_parser import (
    ParsedImageRefEntry,
    ParsedKubeManifest,
    ParseKubeManifestRequest,
)
from pants.backend.helm.testutil import K8S_POD_FILE
from pants.backend.helm.utils.yaml import YamlPath
from pants.engine.fs import CreateDigest, Digest, DigestEntries, FileContent, FileEntry
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *k8s_parser.rules(),
            QueryRule(ParsedKubeManifest, (ParseKubeManifestRequest,)),
            QueryRule(DigestEntries, (Digest,)),
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
    file_entries = rule_runner.request(DigestEntries, [file_digest])

    parsed_manifest = rule_runner.request(
        ParsedKubeManifest,
        [ParseKubeManifestRequest(file=cast(FileEntry, file_entries[0]))],
    )

    expected_image_refs = [
        ParsedImageRefEntry(0, YamlPath.parse("/spec/containers/0/image"), "busybox:1.28"),
        ParsedImageRefEntry(0, YamlPath.parse("/spec/initContainers/0/image"), "busybox:1.29"),
    ]

    assert parsed_manifest.found_image_refs == tuple(expected_image_refs)


def test_parser_returns_no_image_refs(rule_runner: RuleRunner) -> None:
    config_map_contents = dedent(
        """\
        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: foo
        data:
          key: value
        """
    )

    file_digest = rule_runner.request(
        Digest,
        [CreateDigest([FileContent("config_map.yaml", config_map_contents.encode("utf-8"))])],
    )
    file_entries = rule_runner.request(DigestEntries, [file_digest])

    parsed_manifest = rule_runner.request(
        ParsedKubeManifest,
        [ParseKubeManifestRequest(file=cast(FileEntry, file_entries[0]))],
    )

    assert len(parsed_manifest.found_image_refs) == 0
