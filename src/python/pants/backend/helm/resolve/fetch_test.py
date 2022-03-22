# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.resolve import fetch
from pants.backend.helm.resolve.fetch import FetchedHelmArtifacts, FetchHelmArfifactsRequest
from pants.backend.helm.subsystems import helm
from pants.backend.helm.target_types import (
    AllHelmArtifactTargets,
    HelmArtifactFieldSet,
    HelmArtifactTarget,
)
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.util_rules import tool
from pants.core.util_rules import config_files, external_tool
from pants.engine import process
from pants.engine.addresses import Address
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
            *helm.rules(),
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
            "3rdparty/helm/jetstack/BUILD": dedent(
                """\
                helm_artifact(
                  name="cert-manager",
                  repository="@jetstack",
                  artifact="cert-manager",
                  version="v0.7.0"
                )
                """
            ),
        }
    )

    repositories_opts = """{"jetstack": {"address": "https://charts.jetstack.io"}}"""
    rule_runner.set_options([f"--helm-classic-repositories={repositories_opts}"])

    tgt = rule_runner.get_target(Address("3rdparty/helm/jetstack", target_name="cert-manager"))
    fetched_artifacts = rule_runner.request(
        FetchedHelmArtifacts, [FetchHelmArfifactsRequest([HelmArtifactFieldSet.create(tgt)])]
    )
    assert len(fetched_artifacts) == 1
    assert "cert-manager/Chart.yaml" in fetched_artifacts[0].snapshot.files
