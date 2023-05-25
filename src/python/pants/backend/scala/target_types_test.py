# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.scala.target_types import ScalaArtifactExclusion, ScalaArtifactTarget
from pants.backend.scala.target_types import rules as target_types_rules
from pants.build_graph.address import Address
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.internals.parametrize import Parametrize
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.jvm import jvm_common
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
    JvmArtifactExclusion,
    JvmArtifactExclusionsField,
    JvmArtifactGroupField,
    JvmArtifactResolveField,
    JvmArtifactTarget,
    JvmArtifactVersionField,
)
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[ScalaArtifactTarget, JvmArtifactTarget],
        rules=[
            *target_types_rules(),
            *jvm_common.rules(),
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
        ],
        objects={
            "parametrize": Parametrize,
            JvmArtifactExclusion.alias: JvmArtifactExclusion,
            ScalaArtifactExclusion.alias: ScalaArtifactExclusion,
        },
    )
    return rule_runner


_JVM_RESOLVES = {
    "jvm-default": "3rdparty/jvm/default.lock",
    "latest": "3rdparty/jvm/latest.lock",
    "previous": "3rdparty/jvm/previous.lock",
    "current": "3rdparty/jvm/current.lock",
}
_SCALA_VERSION_FOR_RESOLVE = {
    "jvm-default": "2.12.11",
    "latest": "3.3.0",
    "previous": "2.13.10",
    "current": "2.13.9",
}


def assert_generated(
    rule_runner: RuleRunner,
    address: Address,
    *,
    build_content: str,
    expected_targets: set[Target],
) -> None:
    rule_runner.write_files({"BUILD": build_content})
    rule_runner.set_options(
        [
            f"--jvm-resolves={repr(_JVM_RESOLVES)}",
            "--jvm-default-resolve=jvm-default",
            f"--scala-version-for-resolve={repr(_SCALA_VERSION_FOR_RESOLVE)}",
        ]
    )

    parametrizations = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                address,
                description_of_origin="tests",
            ),
        ],
    )
    assert expected_targets == {
        t for parametrization in parametrizations for t in parametrization.parametrization.values()
    }


def test_generate_jvm_artifact_using_default_resolve(rule_runner: RuleRunner) -> None:
    assert_generated(
        rule_runner,
        Address("", target_name="test"),
        build_content=dedent(
            """\
            scala_artifact(
                name="test",
                group="com.example",
                artifact="example-gen",
                version="1.0.0",
            )
            """
        ),
        expected_targets={
            JvmArtifactTarget(
                {
                    JvmArtifactGroupField.alias: "com.example",
                    JvmArtifactArtifactField.alias: "example-gen_2.12",
                    JvmArtifactVersionField.alias: "1.0.0",
                },
                Address(
                    "",
                    target_name="test",
                    generated_name="example-gen_2.12",
                ),
            ),
        },
    )


def test_generate_jvm_artifact_based_on_resolve(rule_runner: RuleRunner) -> None:
    assert_generated(
        rule_runner,
        Address("", target_name="test"),
        build_content=dedent(
            """\
            scala_artifact(
                name="test",
                group="com.example",
                artifact="example-gen",
                version="3.4.0",
                resolve="current",
            )
            """
        ),
        expected_targets={
            JvmArtifactTarget(
                {
                    JvmArtifactGroupField.alias: "com.example",
                    JvmArtifactArtifactField.alias: "example-gen_2.13",
                    JvmArtifactVersionField.alias: "3.4.0",
                    JvmArtifactResolveField.alias: "current",
                },
                Address(
                    "",
                    target_name="test",
                    generated_name="example-gen_2.13",
                ),
            ),
        },
    )


def test_generate_jvm_artifact_using_full_crossversion(rule_runner: RuleRunner) -> None:
    assert_generated(
        rule_runner,
        Address("", target_name="test"),
        build_content=dedent(
            """\
            scala_artifact(
                name="test",
                group="com.example",
                artifact="example-gen",
                version="3.4.0",
                resolve="current",
                crossversion="full",
            )
            """
        ),
        expected_targets={
            JvmArtifactTarget(
                {
                    JvmArtifactGroupField.alias: "com.example",
                    JvmArtifactArtifactField.alias: "example-gen_2.13.9",
                    JvmArtifactVersionField.alias: "3.4.0",
                    JvmArtifactResolveField.alias: "current",
                },
                Address(
                    "",
                    target_name="test",
                    generated_name="example-gen_2.13.9",
                ),
            ),
        },
    )


def test_generate_jvm_artifact_with_exclusions(rule_runner: RuleRunner) -> None:
    assert_generated(
        rule_runner,
        Address("", target_name="test"),
        build_content=dedent(
            """\
            scala_artifact(
                name="test",
                group="com.example",
                artifact="example-gen",
                version="3.4.0",
                resolve="current",
                exclusions=[
                  jvm_exclude(group="com.example"),
                  scala_exclude(group="com.example", artifact="excluded-partial"),
                  scala_exclude(group="com.example", artifact="excluded-full", crossversion="full"),
                ],
            )
            """
        ),
        expected_targets={
            JvmArtifactTarget(
                {
                    JvmArtifactGroupField.alias: "com.example",
                    JvmArtifactArtifactField.alias: "example-gen_2.13",
                    JvmArtifactVersionField.alias: "3.4.0",
                    JvmArtifactResolveField.alias: "current",
                    JvmArtifactExclusionsField.alias: [
                        JvmArtifactExclusion(group="com.example"),
                        JvmArtifactExclusion(group="com.example", artifact="excluded-partial_2.13"),
                        JvmArtifactExclusion(group="com.example", artifact="excluded-full_2.13.9"),
                    ],
                },
                Address(
                    "",
                    target_name="test",
                    generated_name="example-gen_2.13",
                ),
            ),
        },
    )


def test_generate_jvm_artifacts_for_parametrized_resolve(rule_runner: RuleRunner) -> None:
    assert_generated(
        rule_runner,
        Address("", target_name="test"),
        build_content=dedent(
            """\
            scala_artifact(
                name="test",
                group="com.example",
                artifact="example-gen",
                version="2.9.0",
                resolve=parametrize("latest", "previous"),
            )
            """
        ),
        expected_targets={
            JvmArtifactTarget(
                {
                    JvmArtifactGroupField.alias: "com.example",
                    JvmArtifactArtifactField.alias: "example-gen_3",
                    JvmArtifactVersionField.alias: "2.9.0",
                    JvmArtifactResolveField.alias: "latest",
                },
                Address(
                    "",
                    target_name="test",
                    generated_name="example-gen_3",
                    parameters={"resolve": "latest"},
                ),
            ),
            JvmArtifactTarget(
                {
                    JvmArtifactGroupField.alias: "com.example",
                    JvmArtifactArtifactField.alias: "example-gen_2.13",
                    JvmArtifactVersionField.alias: "2.9.0",
                    JvmArtifactResolveField.alias: "previous",
                },
                Address(
                    "",
                    target_name="test",
                    generated_name="example-gen_2.13",
                    parameters={"resolve": "previous"},
                ),
            ),
        },
    )
