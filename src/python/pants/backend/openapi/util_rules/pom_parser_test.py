# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.openapi.util_rules import pom_parser
from pants.backend.openapi.util_rules.pom_parser import AnalysePomRequest, PomReport
from pants.engine.fs import Digest, PathGlobs
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.jvm.resolve.coordinate import Coordinate


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        target_types=[], rules=[*pom_parser.rules(), QueryRule(PomReport, (AnalysePomRequest,))]
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


def test_collects_non_test_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "pom.xml": dedent(
                """\
                <project xmlns = "http://maven.apache.org/POM/4.0.0"
                  xmlns:xsi = "http://www.w3.org/2001/XMLSchema-instance"
                  xsi:schemaLocation = "http://maven.apache.org/POM/4.0.0
                  http://maven.apache.org/xsd/maven-4.0.0.xsd">
                  <modelVersion>4.0.0</modelVersion>

                  <groupId>com.companyname.project-group</groupId>
                  <artifactId>project</artifactId>
                  <version>1.0</version>

                  <properties>
                    <foo.version>1.0</foo.version>
                  </properties>

                  <dependencies>
                    <dependency>
                      <artifactId>foo</artifactId>
                      <groupId>com.example</groupId>
                      <version>${foo.version}</version>
                    </dependency>
                    <dependency>
                      <artifactId>test</artifactId>
                      <groupId>com.example</groupId>
                      <version>1.0</version>
                      <scope>test</scope>
                    </dependency>
                  </dependencies>
                </project>
              """
            )
        }
    )

    digest = rule_runner.request(Digest, [PathGlobs(["pom.xml"])])
    pom_report = rule_runner.request(PomReport, [AnalysePomRequest(digest)])

    assert pom_report.dependencies == (Coordinate("com.example", "foo", "1.0"),)
