# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.build_graph.address import Address
from pants.core.target_types import ResourcesGeneratorTarget, ResourceTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.addresses import Addresses
from pants.jvm import classpath, jdk_rules, resources, testutil
from pants.jvm.goals import lockfile
from pants.jvm.resolve import jvm_tool
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_test_util import EMPTY_JVM_LOCKFILE
from pants.jvm.strip_jar import strip_jar
from pants.jvm.testutil import RenderedClasspath, maybe_skip_jdk_test
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *core_target_types_rules(),
            *coursier_fetch_rules(),
            *lockfile.rules(),
            *jvm_tool.rules(),
            *jdk_rules.rules(),
            *strip_jar.rules(),
            *resources.rules(),
            *classpath.rules(),
            *util_rules(),
            *testutil.rules(),
            QueryRule(RenderedClasspath, (Addresses,)),
        ],
        target_types=[
            ResourcesGeneratorTarget,
            ResourceTarget,
        ],
    )
    rule_runner.set_options(args=[], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


@maybe_skip_jdk_test
def test_resources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": "resources(name='root', sources=['*.txt'])",
            "one.txt": "",
            "two.txt": "",
            "3rdparty/jvm/default.lock": EMPTY_JVM_LOCKFILE,
        }
    )

    # Building the generator target should exclude the individual files and result in a single jar
    # for the generator.
    rendered_classpath = rule_runner.request(
        RenderedClasspath, [Addresses([Address(spec_path="", target_name="root")])]
    )
    assert rendered_classpath.content == {
        ".root.resources.jar": {
            "one.txt",
            "two.txt",
        }
    }

    # But requesting a single file should individually package it.
    rendered_classpath = rule_runner.request(
        RenderedClasspath,
        [Addresses([Address(spec_path="", target_name="root", relative_file_path="one.txt")])],
    )
    assert rendered_classpath.content == {
        ".one.txt.root.resources.jar": {
            "one.txt",
        }
    }
