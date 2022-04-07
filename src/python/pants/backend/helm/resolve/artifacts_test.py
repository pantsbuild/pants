# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.helm.resolve.artifacts import (
    FirstPartyArtifactMapping,
    HelmArtifact,
    HelmArtifactClassicRepositoryLocation,
    HelmArtifactRegistryLocation,
    HelmArtifactRequirement,
    ThirdPartyArtifactMapping,
)
from pants.backend.helm.resolve.artifacts import rules as artifacts_rules
from pants.backend.helm.target_types import (
    AllHelmArtifactTargets,
    HelmArtifactTarget,
    HelmChartTarget,
)
from pants.backend.helm.target_types import rules as target_types_rules
from pants.backend.helm.testutil import (
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
)
from pants.engine.addresses import Address
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.strutil import bullet_list


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmArtifactTarget, HelmChartTarget],
        rules=[
            *artifacts_rules(),
            *target_types_rules(),
            QueryRule(AllHelmArtifactTargets, ()),
            QueryRule(FirstPartyArtifactMapping, ()),
            QueryRule(ThirdPartyArtifactMapping, ()),
        ],
    )


def test_build_first_party_mapping(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": "helm_chart(name='foo')",
            "src/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart-name
                version: 0.1.0
                """
            ),
            "src/values.yaml": HELM_VALUES_FILE,
            "src/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/templates/service.yaml": K8S_SERVICE_FILE,
        }
    )

    tgt = rule_runner.get_target(Address("src", target_name="foo"))
    mapping = rule_runner.request(FirstPartyArtifactMapping, [])
    assert mapping["chart-name"] == tgt.address


def test_duplicate_first_party_artifact_mappings(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/foo/BUILD": "helm_chart()",
            "src/foo/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart-name
                version: 0.1.0
                """
            ),
            "src/foo/values.yaml": HELM_VALUES_FILE,
            "src/foo/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/foo/templates/service.yaml": K8S_SERVICE_FILE,
            "src/bar/BUILD": "helm_chart()",
            "src/bar/Chart.yaml": dedent(
                """\
                apiVersion: v2
                name: chart-name
                version: 0.1.0
                """
            ),
            "src/bar/values.yaml": HELM_VALUES_FILE,
            "src/bar/templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "src/bar/templates/service.yaml": K8S_SERVICE_FILE,
        }
    )

    expected_err_msg = (
        "Found more than one `helm_chart` target using the same chart name:\n\n"
        f"{bullet_list(['src/bar:bar -> chart-name', 'src/foo:foo -> chart-name'])}"
    )

    with pytest.raises(ExecutionError) as err_info:
        rule_runner.request(FirstPartyArtifactMapping, [])

    assert expected_err_msg in err_info.value.args[0]


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
        requirement=HelmArtifactRequirement(
            name="foo",
            version="0.1.0",
            location=HelmArtifactRegistryLocation(
                registry="oci://www.example.com", repository="charts"
            ),
        ),
        address=Address("3rdparty/helm/example", target_name="foo"),
    )
    expected_bar = HelmArtifact(
        requirement=HelmArtifactRequirement(
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
