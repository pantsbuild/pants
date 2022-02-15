# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import PurePath
from typing import cast

import pytest

from pants.backend.helm.goals.package import BuiltHelmArtifact
from pants.backend.helm.goals.publish import HelmPublishFieldSet, PublishHelmChartRequest
from pants.backend.helm.goals.publish import rules as publish_rules
from pants.backend.helm.subsystem import HelmSubsystem
from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.util_rules import tool
from pants.backend.helm.util_rules.chart import HelmChartMetadata
from pants.backend.helm.util_rules.tool import HelmBinary
from pants.core.goals.package import BuiltPackage
from pants.core.goals.publish import PublishPackages, PublishProcesses
from pants.core.util_rules import external_tool
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST
from pants.engine.rules import SubsystemRule
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *external_tool.rules(),
            *publish_rules(),
            *tool.rules(),
            SubsystemRule(HelmSubsystem),
            QueryRule(PublishProcesses, [PublishHelmChartRequest]),
            QueryRule(HelmBinary, []),
        ],
        target_types=[HelmChartTarget],
    )
    rule_runner.write_files(
        {
            "src/missing-registries/BUILD": """helm_chart()""",
            "src/skip-test/BUILD": """helm_chart(skip_push=True)""",
            "src/registries/BUILD": """helm_chart(registries=["@internal", "oci://www.example.com/external"])""",
            "src/repository/BUILD": """helm_chart(registries=["oci://www.example.com/external"], repository="mycharts")""",
        }
    )
    return rule_runner


def _build(target: HelmChartTarget, metadata: HelmChartMetadata) -> tuple[BuiltPackage, ...]:
    return (BuiltPackage(EMPTY_DIGEST, (BuiltHelmArtifact.create(PurePath("dist"), metadata),)),)


def _run_publish(
    rule_runner: RuleRunner,
    address: Address,
    metadata: HelmChartMetadata,
    options: dict | None = None,
) -> tuple[PublishProcesses, HelmBinary]:
    opts = options or {}
    opts.setdefault("--helm-registries", {})
    opt_args = [f"{name}={repr(value)}" for name, value in opts.items()]
    rule_runner.set_options(opt_args)

    target = cast(HelmChartTarget, rule_runner.get_target(address))
    field_set = HelmPublishFieldSet.create(target)
    packages = _build(target, metadata)
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
        expect_process(publish.process)
    else:
        assert publish.process is None


def process_assertion(**assertions):
    def assert_process(process):
        for attr, expected in assertions.items():
            assert getattr(process, attr) == expected

    return assert_process


def test_helm_skip_push(rule_runner: RuleRunner) -> None:
    chart_metadata = HelmChartMetadata("foo-chart", "0.1.0")
    result, _ = _run_publish(rule_runner, Address("src/skip-test"), chart_metadata)
    assert len(result) == 1
    assert_publish(
        result[0],
        ("charts/foo-chart-0.1.0",),
        "(by `skip_push` on src/skip-test:skip-test)",
        None,
    )


def test_helm_push_no_charts_when_registries_are_not_set(rule_runner: RuleRunner) -> None:
    chart_metadata = HelmChartMetadata("missing-registries", "0.1.0")
    result, _ = _run_publish(rule_runner, Address("src/missing-registries"), chart_metadata)
    assert len(result) == 1
    assert_publish(
        result[0],
        ("charts/missing-registries-0.1.0",),
        "(by missing `registries` on src/missing-registries:missing-registries)",
        None,
    )


def test_helm_push_using_default_registries(rule_runner: RuleRunner) -> None:
    opts = {
        "--helm-registries": {
            "internal": {"address": "oci://www.example.com/internal", "default": "true"}
        }
    }
    chart_metadata = HelmChartMetadata("missing-registries", "0.1.0")
    result, helm = _run_publish(
        rule_runner, Address("src/missing-registries"), chart_metadata, opts
    )
    assert len(result) == 1
    assert_publish(
        result[0],
        ("oci://www.example.com/internal/charts/missing-registries-0.1.0",),
        None,
        process_assertion(
            argv=(
                helm.path,
                "push",
                "dist/missing-registries-0.1.0.tgz",
                "oci://www.example.com/internal/charts",
            )
        ),
    )


def test_helm_push_registries(rule_runner: RuleRunner) -> None:
    opts = {"--helm-registries": {"internal": {"address": "oci://www.example.com/internal"}}}
    chart_metadata = HelmChartMetadata("registries", "0.1.0")
    result, helm = _run_publish(rule_runner, Address("src/registries"), chart_metadata, opts)
    assert len(result) == 2
    assert_publish(
        result[0],
        ("oci://www.example.com/internal/charts/registries-0.1.0",),
        None,
        process_assertion(
            argv=(
                helm.path,
                "push",
                "dist/registries-0.1.0.tgz",
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
                "dist/registries-0.1.0.tgz",
                "oci://www.example.com/external/charts",
            )
        ),
    )


def test_helm_push_registries_with_custom_repository(rule_runner: RuleRunner) -> None:
    chart_metadata = HelmChartMetadata("repository", "0.1.0")
    result, helm = _run_publish(rule_runner, Address("src/repository"), chart_metadata)
    assert len(result) == 1
    assert_publish(
        result[0],
        ("oci://www.example.com/external/mycharts/repository-0.1.0",),
        None,
        process_assertion(
            argv=(
                helm.path,
                "push",
                "dist/repository-0.1.0.tgz",
                "oci://www.example.com/external/mycharts",
            )
        ),
    )
