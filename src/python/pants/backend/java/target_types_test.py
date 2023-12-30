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
    JvmArtifactGroupField,
    JvmArtifactsTargetGenerator,
    JvmArtifactTarget,
    JvmArtifactVersionField,
)
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[ScalaArtifactTarget, JvmArtifactTarget, JvmArtifactsTargetGenerator],
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


def test_generate_jvm_artifacts_from_pom_xml(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "pom.xml": dedent(
                """\
<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.pulsepoint</groupId>
  <artifactId>dpd-etl</artifactId>
  <version>0.1.0</version>
  <build>
    <sourceDirectory>${project.basedir}/src/jvm</sourceDirectory>
    <testSourceDirectory>${project.basedir}/tests/jvm</testSourceDirectory>
  </build>
  <properties>
    <maven.compiler.source>1.17</maven.compiler.source>
    <maven.compiler.target>1.17</maven.compiler.target>
  </properties>
  <dependencies>
    <dependency>
      <groupId>com.google.guava</groupId>
      <artifactId>guava</artifactId>
      <version>14.0.1</version>
    </dependency>
    <dependency>
      <groupId>org.apache.logging.log4j</groupId>
      <artifactId>log4j-api</artifactId>
      <version>2.19.0</version>
    </dependency>
  </dependencies>
</project>
                """
            ),
        }
    )
    assert_generated(
        rule_runner,
        Address("", target_name="test"),
        build_content=dedent(
            """\
            jvm_artifacts(name="test")
            """
        ),
        expected_targets={
            JvmArtifactTarget(
                {
                    JvmArtifactGroupField.alias: "com.google.guava",
                    JvmArtifactArtifactField.alias: "guava",
                    JvmArtifactVersionField.alias: "14.0.1",
                },
                Address(
                    "",
                    target_name="test",
                    generated_name="guava",
                ),
            ),
            JvmArtifactTarget(
                {
                    JvmArtifactGroupField.alias: "org.apache.logging.log4j",
                    JvmArtifactArtifactField.alias: "log4j-api",
                    JvmArtifactVersionField.alias: "2.19.0",
                },
                Address(
                    "",
                    target_name="test",
                    generated_name="log4j-api",
                ),
            ),
        },
    )
