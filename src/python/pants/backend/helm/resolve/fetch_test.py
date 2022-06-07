# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.resolve import fetch
from pants.backend.helm.resolve.artifacts import HelmArtifact, ResolvedHelmArtifact
from pants.backend.helm.resolve.fetch import FetchedHelmArtifacts, FetchHelmArfifactsRequest
from pants.backend.helm.target_types import AllHelmArtifactTargets, HelmArtifactTarget
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.util_rules import process as helm_process
from pants.core.util_rules import config_files, external_tool
from pants.engine import process
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmArtifactTarget],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *fetch.rules(),
            *helm_process.rules(),
            *process.rules(),
            *target_types_rules(),
            QueryRule(AllHelmArtifactTargets, ()),
            QueryRule(ResolvedHelmArtifact, (HelmArtifact,)),
            QueryRule(FetchedHelmArtifacts, (FetchHelmArfifactsRequest,)),
        ],
    )


def test_download_artifacts(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/helm/BUILD": dedent(
                """\
                helm_artifact(
                  name="cert-manager",
                  repository="https://charts.jetstack.io/",
                  artifact="cert-manager",
                  version="v1.7.1"
                )

                helm_artifact(
                    name="prometheus-stack",
                    repository="https://prometheus-community.github.io/helm-charts",
                    artifact="kube-prometheus-stack",
                    version="^27.2.0"
                )
                """
            ),
        }
    )

    targets = rule_runner.request(AllHelmArtifactTargets, [])
    fetched_artifacts = rule_runner.request(
        FetchedHelmArtifacts,
        [
            FetchHelmArfifactsRequest.for_targets(
                targets, description_of_origin="test_download_artifacts"
            )
        ],
    )

    expected_artifacts = [
        rule_runner.request(ResolvedHelmArtifact, [HelmArtifact.from_target(tgt)])
        for tgt in targets
    ]

    assert len(fetched_artifacts) == len(expected_artifacts)
    for fetched, expected in zip(fetched_artifacts, expected_artifacts):
        assert fetched.artifact == expected
        assert f"{expected.name}/Chart.yaml" in fetched.snapshot.files
