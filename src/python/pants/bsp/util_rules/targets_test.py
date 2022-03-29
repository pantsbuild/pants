# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import textwrap

import pytest

from pants.bsp.rules import rules as bsp_rules
from pants.bsp.util_rules.targets import BSPBuildTargets, BSPTargetDefinition
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *bsp_rules(),
            QueryRule(BSPBuildTargets, ()),
        ]
    )


def test_config_file_parsing(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "first.toml": textwrap.dedent(
                """\
            [targets.foo]
            display_name = "Foo"
            base_directory = "src/jvm"
            addresses = ["src/jvm::"]
            resolve = "jvm:jvm-default"
            """
            ),
            "second.toml": textwrap.dedent(
                """\
            [targets.foo]
            display_name = "Foo for My Team"
            base_directory = "src/jvm"
            addresses = ["src/jvm::", "my-team/src/jvm::"]
            resolve = "jvm:jvm-default"

            [targets.bar]
            display_name = "Bar"
            base_directory = "bar/src/jvm"
            addresses = ["bar/src/jvm::"]
            resolve = "jvm:bar"
            """
            ),
        }
    )
    rule_runner.set_options(
        ["--experimental-bsp-targets-config-files=['first.toml', 'second.toml']"]
    )

    bsp_build_targets = rule_runner.request(BSPBuildTargets, ())

    definitions = {
        (name, btgt.definition) for name, btgt in bsp_build_targets.targets_mapping.items()
    }
    assert definitions == {
        (
            "foo",
            BSPTargetDefinition(
                display_name="Foo for My Team",
                base_directory="src/jvm",
                addresses=("src/jvm::", "my-team/src/jvm::"),
                resolve_filter="jvm:jvm-default",
            ),
        ),
        (
            "bar",
            BSPTargetDefinition(
                display_name="Bar",
                base_directory="bar/src/jvm",
                addresses=("bar/src/jvm::",),
                resolve_filter="jvm:bar",
            ),
        ),
    }
