# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.resolve.artifacts import (
    HelmArtifact,
    HelmArtifactClassicRepositoryLocation,
    HelmArtifactMetadata,
    HelmArtifactRegistryLocation,
    ThirdPartyArtifactMapping,
)
from pants.backend.helm.resolve.artifacts import rules as artifacts_rules
from pants.backend.helm.target_types import AllHelmArtifactTargets, HelmArtifactTarget
from pants.backend.helm.target_types import rules as target_types_rules
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmArtifactTarget],
        rules=[
            *artifacts_rules(),
            *target_types_rules(),
            QueryRule(AllHelmArtifactTargets, ()),
            QueryRule(ThirdPartyArtifactMapping, ()),
        ],
    )


def test_build_third_party_mapping(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/helm/example/BUILD": dedent(
                """\
                helm_artifact(
                  name="foo",
                  registry="oci://www.example.com",
                  repository="charts",
                  artifact="foo",
                  version="0.1.0",
                )
                helm_artifact(
                  name="bar",
                  repository="@example",
                  artifact="bar",
                  version="0.1.0",
                )
                """
            )
        }
    )

    expected_foo = HelmArtifact(
        metadata=HelmArtifactMetadata(
            name="foo",
            version="0.1.0",
            location=HelmArtifactRegistryLocation(
                registry="oci://www.example.com", repository="charts"
            ),
        ),
        address=Address("3rdparty/helm/example", target_name="foo"),
    )
    expected_bar = HelmArtifact(
        metadata=HelmArtifactMetadata(
            name="bar",
            version="0.1.0",
            location=HelmArtifactClassicRepositoryLocation("@example"),
        ),
        address=Address("3rdparty/helm/example", target_name="bar"),
    )

    repositories_opts = """{"example": {"address": "https://www.example.com/charts"}}"""
    rule_runner.set_options([f"--helm-classic-repositories={repositories_opts}"])

    tgts = rule_runner.request(AllHelmArtifactTargets, [])
    artifacts = [HelmArtifact.from_target(tgt) for tgt in tgts]

    assert len(artifacts) == 2
    assert expected_foo in artifacts
    assert expected_bar in artifacts

    mapping = rule_runner.request(ThirdPartyArtifactMapping, [])
    assert mapping["oci://www.example.com/charts/foo"] == expected_foo.address
    assert mapping["example/bar"] == expected_bar.address
