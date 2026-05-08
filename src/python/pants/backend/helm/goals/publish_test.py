# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Iterable
from textwrap import dedent
from typing import cast
from unittest.mock import Mock

import pytest

from pants.backend.helm.goals import publish
from pants.backend.helm.goals.package import BuiltHelmArtifact, HelmPackageFieldSet
from pants.backend.helm.goals.publish import (
    HelmPublishFieldSet,
    PublishHelmChartRequest,
    PublishHelmChartSkipRequest,
    check_if_skip_push,
)
from pants.backend.helm.subsystems.helm import HelmSubsystem
from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.chart import HelmChart, HelmChartRequest
from pants.backend.helm.util_rules.chart_metadata import HelmChartMetadata
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.goals.package import BuiltPackage
from pants.core.goals.publish import (
    CheckSkipResult,
    PublishOutputData,
    PublishPackages,
    PublishProcesses,
)
from pants.core.util_rules import external_tool
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.process import InteractiveProcess
from pants.testutil.option_util import create_subsystem
from pants.testutil.process_util import process_assertion
from pants.testutil.rule_runner import QueryRule, RuleRunner, run_rule_with_mocks


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *external_tool.rules(),
            *publish.rules(),
            *tool.rules(),
            QueryRule(PublishProcesses, [PublishHelmChartRequest]),
            QueryRule(HelmBinary, []),
        ],
        target_types=[HelmChartTarget],
    )


def _build(metadata: HelmChartMetadata) -> tuple[BuiltPackage, ...]:
    return (
        BuiltPackage(
            EMPTY_DIGEST, (BuiltHelmArtifact.create(f"{metadata.artifact_name}.tgz", metadata),)
        ),
    )


def _run_publish(
    rule_runner: RuleRunner,
    address: Address,
    metadata: HelmChartMetadata,
    *,
    registries: dict | None = None,
    default_repo: str | None = None,
) -> tuple[PublishProcesses, HelmBinary]:
    opts: dict[str, str] = {}
    opts.setdefault("--helm-registries", "{}")

    if registries:
        opts["--helm-registries"] = repr(registries)
    if default_repo:
        opts["--helm-default-registry-repository"] = default_repo

    rule_runner.set_options([f"{key}={value}" for key, value in opts.items()])

    target = cast(HelmChartTarget, rule_runner.get_target(address))
    field_set = HelmPublishFieldSet.create(target)
    packages = _build(metadata)

    result = rule_runner.request(PublishProcesses, [field_set._request(packages)])
    helm = rule_runner.request(HelmBinary, [])
    return result, helm


def assert_publish(
    publish: PublishPackages,
    expect_names: tuple[str, ...],
    expect_description: str | None,
    expect_process,
) -> None:
    assert publish.names == expect_names
    assert publish.description == expect_description
    if expect_process:
        assert publish.process
        assert isinstance(publish.process, InteractiveProcess)
        expect_process(publish.process.process)
    else:
        assert publish.process is None


def _declare_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/missing-registries/BUILD": """helm_chart()""",
            "src/skip-push/BUILD": """helm_chart(skip_push=True)""",
            "src/registries/BUILD": dedent(
                """\
                helm_chart(registries=["@internal", "oci://www.example.com/external"])
                """
            ),
            "src/repository/BUILD": dedent(
                """\
                helm_chart(registries=["oci://www.example.com/external"], repository="mycharts")
                """
            ),
        }
    )


def get_publish_output_data(target: Address, registries: Iterable[str]) -> PublishOutputData:
    return PublishOutputData(
        {
            "publisher": "helm",
            "target": target,
            "registries": tuple(registries),
        }
    )


MISSING_REGISTRIES_ADDRESS = Address("src/missing-registries")
SKIP_PUSH_ADDRESS = Address("src/skip-push")
REGISTRIES_ADDRESS = Address("src/registries")
REPOSITORY_ADDRESS = Address("src/repository")


@pytest.mark.parametrize(
    ["address", "default_registry", "expected"],
    [
        pytest.param(
            REGISTRIES_ADDRESS,
            False,
            CheckSkipResult.no_skip(),
            id="no_skip_has_registries_and_skip_push_false",
        ),
        pytest.param(
            MISSING_REGISTRIES_ADDRESS,
            False,
            CheckSkipResult.skip(
                names=["missing-registries-0.1.0"],
                description="(by missing `registries` on src/missing-registries:missing-registries)",
                data=get_publish_output_data(
                    MISSING_REGISTRIES_ADDRESS, ["<ALL DEFAULT HELM REGISTRIES>"]
                ),
            ),
            id="skip_missing_registries",
        ),
        pytest.param(
            SKIP_PUSH_ADDRESS,
            True,
            CheckSkipResult.skip(
                names=["skip-push-0.1.0"],
                description="(by `skip_push` on src/skip-push:skip-push)",
                data=get_publish_output_data(SKIP_PUSH_ADDRESS, ["<ALL DEFAULT HELM REGISTRIES>"]),
            ),
            id="skip_explicit_skip_push_true",
        ),
        pytest.param(
            MISSING_REGISTRIES_ADDRESS,
            True,
            CheckSkipResult.no_skip(),
            id="no_skip_missing_registries_and_default_repo_true",
        ),
    ],
)
def test_check_if_skip_push(
    rule_runner: RuleRunner,
    address: Address,
    default_registry: bool,
    expected: CheckSkipResult,
) -> None:
    _declare_targets(rule_runner)

    artifact_name = expected.skipped_packages[0].names[0] if expected.skipped_packages else None
    helm_subsystem = create_subsystem(
        HelmSubsystem,
        registries={"internal": {"address": "oci://www.example.com", "default": default_registry}},
    )
    tgt = rule_runner.get_target(address)
    publish_fs = HelmPublishFieldSet.create(tgt)
    package_fs = HelmPackageFieldSet.create(tgt)

    def mock_get_helm_chart(request: HelmChartRequest) -> HelmChart:
        assert request.field_set == publish_fs
        mock_helm_chart = Mock(spec=HelmChart)
        mock_info = Mock(spec=HelmChartMetadata)
        mock_info.artifact_name = artifact_name
        mock_helm_chart.info = mock_info
        return mock_helm_chart

    mock_calls = (
        {"pants.backend.helm.util_rules.chart.get_helm_chart": mock_get_helm_chart}
        if artifact_name
        else None
    )
    result = run_rule_with_mocks(
        check_if_skip_push,
        rule_args=[
            PublishHelmChartSkipRequest(publish_fs=publish_fs, package_fs=package_fs),
            helm_subsystem,
        ],
        mock_calls=mock_calls,
    )
    assert result == expected


def test_helm_push_use_default_registries(rule_runner: RuleRunner) -> None:
    _declare_targets(rule_runner)

    registries = {"internal": {"address": "oci://www.example.com", "default": True}}
    chart_metadata = HelmChartMetadata("missing-registries", "0.2.0")
    result, helm = _run_publish(
        rule_runner, Address("src/missing-registries"), chart_metadata, registries=registries
    )

    assert len(result) == 1
    assert_publish(
        result[0],
        ("oci://www.example.com/missing-registries-0.2.0",),
        None,
        process_assertion(
            argv=(helm.path, "push", "missing-registries-0.2.0.tgz", "oci://www.example.com")
        ),
    )


def test_helm_push_registries(rule_runner: RuleRunner) -> None:
    _declare_targets(rule_runner)

    registries = {"internal": {"address": "oci://www.example.com/internal"}}
    chart_metadata = HelmChartMetadata("registries", "0.1.0")
    result, helm = _run_publish(
        rule_runner,
        Address("src/registries"),
        chart_metadata,
        registries=registries,
        default_repo="charts",
    )

    assert len(result) == 2
    assert_publish(
        result[0],
        ("oci://www.example.com/internal/charts/registries-0.1.0",),
        None,
        process_assertion(
            argv=(
                helm.path,
                "push",
                "registries-0.1.0.tgz",
                "oci://www.example.com/internal/charts",
            )
        ),
    )
    assert_publish(
        result[1],
        ("oci://www.example.com/external/charts/registries-0.1.0",),
        None,
        process_assertion(
            argv=(
                helm.path,
                "push",
                "registries-0.1.0.tgz",
                "oci://www.example.com/external/charts",
            )
        ),
    )


def test_helm_push_registries_with_custom_repository(rule_runner: RuleRunner) -> None:
    _declare_targets(rule_runner)

    chart_metadata = HelmChartMetadata("repository", "0.1.0")
    result, helm = _run_publish(
        rule_runner, Address("src/repository"), chart_metadata, default_repo="default_charts"
    )
    assert len(result) == 1
    assert_publish(
        result[0],
        ("oci://www.example.com/external/mycharts/repository-0.1.0",),
        None,
        process_assertion(
            argv=(
                helm.path,
                "push",
                "repository-0.1.0.tgz",
                "oci://www.example.com/external/mycharts",
            )
        ),
    )
