# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.resolve import fetch
from pants.backend.helm.resolve.artifacts import HelmArtifact
from pants.backend.helm.resolve.fetch import FetchedHelmArtifacts, FetchHelmArfifactsRequest
from pants.backend.helm.target_types import AllHelmArtifactTargets, HelmArtifactTarget
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.util_rules import tool
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
            *tool.rules(),
            *process.rules(),
            *target_types_rules(),
            QueryRule(AllHelmArtifactTargets, ()),
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
                  repository="@jetstack",
                  artifact="cert-manager",
                  version="v0.7.0"
                )

                helm_artifact(
                    name="prometheus-stack",
                    repository="@prometheus",
                    artifact="kube-prometheus-stack",
                    version="^27.2.0"
                )
                """
            ),
        }
    )

    repositories_opts = {
        "jetstack": {"address": "https://charts.jetstack.io"},
        "prometheus": {"address": "https://prometheus-community.github.io/helm-charts"},
    }
    rule_runner.set_options([f"--helm-classic-repositories={repr(repositories_opts)}"])

    targets = rule_runner.request(AllHelmArtifactTargets, [])
    fetched_artifacts = rule_runner.request(
        FetchedHelmArtifacts, [FetchHelmArfifactsRequest.for_targets(targets)]
    )

    expected_artifacts = [HelmArtifact.from_target(tgt) for tgt in targets]

    assert len(fetched_artifacts) == len(expected_artifacts)
    for fetched, expected in zip(fetched_artifacts, expected_artifacts):
        assert fetched.artifact == expected
        assert f"{expected.name}/Chart.yaml" in fetched.snapshot.files
