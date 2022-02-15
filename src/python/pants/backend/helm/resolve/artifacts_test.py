# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.resolve import artifacts
from pants.backend.helm.resolve.artifacts import (
    AllHelmArtifactTargets,
    AllThirdPartyArtifacts,
    HelmArtifact,
    RegistryLocation,
    RepositoryLocation,
    ThirdPartyArtifactMapping,
)
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import (
    HelmArtifactArtifactField,
    HelmArtifactRegistryField,
    HelmArtifactRepositoryField,
    HelmArtifactTarget,
    HelmArtifactVersionField,
)
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule, SubsystemRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmArtifactTarget],
        rules=[
            *artifacts.rules(),
            SubsystemRule(HelmSubsystem),
            QueryRule(AllHelmArtifactTargets, ()),
            QueryRule(AllThirdPartyArtifacts, ()),
            QueryRule(ThirdPartyArtifactMapping, ()),
        ],
    )


def test_filter_helm_artifact_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/helm/foo/BUILD": dedent(
                """\
                helm_artifact(
                  registry="oci://www.example.com",
                  repository="charts",
                  artifact="foo",
                  version="0.1.0",
                )
                """
            )
        }
    )

    all_targets = rule_runner.request(AllHelmArtifactTargets, [])

    assert len(all_targets) == 1
    assert all_targets[0][HelmArtifactArtifactField].value == "foo"
    assert all_targets[0][HelmArtifactVersionField].value == "0.1.0"
    assert all_targets[0][HelmArtifactRegistryField].value == "oci://www.example.com"
    assert all_targets[0][HelmArtifactRepositoryField].value == "charts"


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
                  repository="https://www.example.com/charts",
                  artifact="bar",
                  version="0.1.0",
                )
                """
            )
        }
    )

    expected_foo = HelmArtifact(
        name="foo",
        version="0.1.0",
        address=Address("3rdparty/helm/example", target_name="foo"),
        location=RegistryLocation(registry="oci://www.example.com", repository="charts"),
    )
    expected_bar = HelmArtifact(
        name="bar",
        version="0.1.0",
        address=Address("3rdparty/helm/example", target_name="bar"),
        location=RepositoryLocation("https://www.example.com/charts"),
    )

    artifacts = rule_runner.request(AllThirdPartyArtifacts, [])
    assert len(artifacts) == 2
    assert expected_foo in artifacts
    assert expected_bar in artifacts

    mapping = rule_runner.request(ThirdPartyArtifactMapping, [])
    assert mapping["oci://www.example.com/charts/foo"] == expected_foo.address
    assert mapping["https://www.example.com/charts/bar"] == expected_bar.address
