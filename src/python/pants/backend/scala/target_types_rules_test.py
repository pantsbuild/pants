# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.scala.target_types import ScalaArtifactExclusionRule, ScalaArtifactTarget
from pants.backend.scala.target_types_rules import rules as target_types_rules
from pants.build_graph.address import Address
from pants.engine.internals.graph import _TargetParametrizations, _TargetParametrizationsRequest
from pants.engine.internals.parametrize import Parametrize
from pants.engine.rules import QueryRule
from pants.jvm.target_types import (
    JvmArtifactArtifactField,
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
            QueryRule(_TargetParametrizations, [_TargetParametrizationsRequest]),
        ],
        objects={
            "parametrize": Parametrize,
            ScalaArtifactExclusionRule.alias: ScalaArtifactExclusionRule,
        },
    )
    return rule_runner


def test_scala_artifacts_per_resolve(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "3rdparty/jvm/BUILD": dedent(
                """\
                jvm_artifact(
                    name="scala_2",
                    group="org.scala-lang",
                    artifact="scala-library",
                    version="2.13.10",
                )

                jvm_artifact(
                    name="scala_3",
                    group="org.scala-lang",
                    artifact="scala3-library",
                    version="3.3.0"
                )

                scala_artifact(
                    name="cats",
                    group="org.typelevel",
                    artifact="cats-core",
                    version="2.9.0",
                    resolve=parametrize("jvm-default", "spark")
                )

                scala_artifact(
                    name="spark",
                    group="org.apache.spark",
                    artifact="spark-core",
                    version="3.4.0",
                    resolve="spark"
                )
                """
            ),
        }
    )

    scala_versions = {"jvm-default": "3.3.0", "spark": "2.13.10"}
    rule_runner.set_options([f"--scala-version-for-resolve={repr(scala_versions)}"])

    generated_cats_artifacts = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address("3rdparty/jvm", target_name="cats"),
                description_of_origin="the test test_scala_artifacts_per_resolve",
            )
        ],
    ).parametrizations

    generated_spark_artifacts = rule_runner.request(
        _TargetParametrizations,
        [
            _TargetParametrizationsRequest(
                Address("3rdparty/jvm", target_name="spark"),
                description_of_origin="the test test_scala_artifacts_per_resolve",
            )
        ],
    ).parametrizations

    generated_targets = set(generated_cats_artifacts.values()).union(
        set(generated_spark_artifacts.values())
    )
    expected_generated_tgts = {
        JvmArtifactTarget(
            {
                JvmArtifactGroupField.alias: "org.typelevel",
                JvmArtifactArtifactField.alias: "cats-core_3",
                JvmArtifactVersionField.alias: "2.9.0",
                JvmArtifactResolveField.alias: "jvm-default",
            },
            Address(
                "3rdparty/jvm",
                target_name="cats",
                generated_name="cats-core_3",
                parameters={"resolve": "jvm-default"},
            ),
        ),
        JvmArtifactTarget(
            {
                JvmArtifactGroupField.alias: "org.typelevel",
                JvmArtifactArtifactField.alias: "cats-core_2.13",
                JvmArtifactVersionField.alias: "2.9.0",
                JvmArtifactResolveField.alias: "spark",
            },
            Address(
                "3rdparty/jvm",
                target_name="cats",
                generated_name="cats-core_2.13",
                parameters={"resolve": "spark"},
            ),
        ),
        JvmArtifactTarget(
            {
                JvmArtifactGroupField.alias: "org.apache.spark",
                JvmArtifactArtifactField.alias: "spark-core_2.13",
                JvmArtifactVersionField.alias: "3.4.0",
                JvmArtifactResolveField.alias: "spark",
            },
            Address(
                "3rdparty/jvm",
                target_name="spark",
                generated_name="spark-core_2.13",
                parameters={"resolve": "spark"},
            ),
        ),
    }
    assert generated_targets == expected_generated_tgts
