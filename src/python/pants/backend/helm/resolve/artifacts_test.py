# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.resolve.artifacts import (
    HelmArtifact,
    HelmArtifactClassicRepositoryLocationSpec,
    HelmArtifactRegistryLocationSpec,
    HelmArtifactRequirement,
    ThirdPartyHelmArtifactMapping,
)
from pants.backend.helm.resolve.artifacts import rules as artifacts_rules
from pants.backend.helm.target_types import (
    AllHelmArtifactTargets,
    HelmArtifactTarget,
    HelmChartTarget,
)
from pants.backend.helm.target_types import rules as target_types_rules
from pants.engine.addresses import Address
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmArtifactTarget, HelmChartTarget],
        rules=[
            *artifacts_rules(),
            *target_types_rules(),
            QueryRule(AllHelmArtifactTargets, ()),
            QueryRule(ThirdPartyHelmArtifactMapping, ()),
        ],
    )


def test_build_third_party_mapping(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/helm/example/BUILD": dedent(
                """\
                helm_artifact(
                  name="foo",
                  registry="oci://www.example.com/",
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
                helm_artifact(
                  name="quux",
                  registry="@quux",
                  repository="quux-charts",
                  artifact="quux",
                  version="0.1.0",
                )
                """
            )
        }
    )

    expected_foo = HelmArtifact(
        requirement=HelmArtifactRequirement(
            name="foo",
            version="0.1.0",
            location=HelmArtifactRegistryLocationSpec(
                registry="oci://www.example.com", repository="charts"
            ),
        ),
        address=Address("3rdparty/helm/example", target_name="foo"),
    )
    expected_bar = HelmArtifact(
        requirement=HelmArtifactRequirement(
            name="bar",
            version="0.1.0",
            location=HelmArtifactClassicRepositoryLocationSpec("https://www.example.com/charts"),
        ),
        address=Address("3rdparty/helm/example", target_name="bar"),
    )
    expected_quux = HelmArtifact(
        requirement=HelmArtifactRequirement(
            name="quux",
            version="0.1.0",
            location=HelmArtifactRegistryLocationSpec(registry="@quux", repository="quux-charts"),
        ),
        address=Address("3rdparty/helm/example", target_name="quux"),
    )

    registries_opts = """{"quux": {"address": "oci://www.example.com"}}"""
    rule_runner.set_options(
        [
            f"--helm-registries={registries_opts}",
        ]
    )

    tgts = rule_runner.request(AllHelmArtifactTargets, [])
    artifacts = [HelmArtifact.from_target(tgt) for tgt in tgts]

    assert len(artifacts) == 3
    assert expected_foo in artifacts
    assert expected_bar in artifacts
    assert expected_quux in artifacts

    mapping = rule_runner.request(ThirdPartyHelmArtifactMapping, [])
    assert len(mapping) == 3
    assert mapping["oci://www.example.com/charts/foo"] == expected_foo.address
    assert mapping["https://www.example.com/charts/bar"] == expected_bar.address
    assert mapping["oci://www.example.com/quux-charts/quux"] == expected_quux.address
