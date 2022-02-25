# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.resolve import artifacts, fetch
from pants.backend.helm.resolve.artifacts import AllHelmArtifactTargets
from pants.backend.helm.resolve.fetch import FetchedHelmArtifacts, FetchHelmArfifactsRequest
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import HelmArtifactFieldSet, HelmArtifactTarget
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.util_rules import config_files, external_tool
from pants.engine import process
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule, SubsystemRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmArtifactTarget],
        rules=[
            *config_files.rules(),
            *external_tool.rules(),
            *artifacts.rules(),
            *fetch.rules(),
            *tool.rules(),
            *process.rules(),
            SubsystemRule(HelmSubsystem),
            QueryRule(AllHelmArtifactTargets, ()),
            QueryRule(HelmBinary, ()),
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
    rule_runner.set_options([f"--helm-registries={repositories_opts}"])

    tgt = rule_runner.get_target(Address("3rdparty/helm/jetstack", target_name="cert-manager"))
    fetched_artifacts = rule_runner.request(
        FetchedHelmArtifacts, [FetchHelmArfifactsRequest([HelmArtifactFieldSet.create(tgt)])]
    )
    assert len(fetched_artifacts) == 1
    assert "cert-manager/Chart.yaml" in fetched_artifacts[0].snapshot.files
